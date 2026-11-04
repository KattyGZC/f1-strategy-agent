import asyncio
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from f1_strategy.application.replay import (
    ControlReplay,
    ProduceReplay,
    ReplayEnd,
    ReplayNotFoundError,
    ReplayPolicy,
    ReplayProducers,
    ReplayState,
    SessionNotLoadedError,
    StartReplay,
    TooManyReplaysError,
)
from f1_strategy.domain.clean import Position, clean_session
from f1_strategy.domain.playback import Paused, Playing, ReplaySpeed, started
from f1_strategy.domain.replay import Event, TimelineRows, timeline
from tests.factories import FakeClock
from tests.replay_rows import Rows
from tests.samples import RACE, sample

pytestmark = pytest.mark.anyio

SESSION = 9472
OTHER_SESSION = 9468
T0 = datetime(2024, 3, 2, 15, tzinfo=UTC)
OFFSETS_S = (0.0, 1.5, 4.0, 10.0)
POLICY = ReplayPolicy(tick_s=0.25, lease_s=5.0)
OWNER = "this-process"
REPLAY = "replay-1"

type Action = Callable[[], Awaitable[object]]


async def until(condition: Callable[[], bool]) -> None:
    for _ in range(10_000):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("the condition never held")


def positions_at(offsets_s: Sequence[float]) -> Rows:
    return Rows(
        positions=[
            Position(SESSION, index + 1, T0 + timedelta(seconds=offset_s), index + 1)
            for index, offset_s in enumerate(offsets_s)
        ]
    )


class ScriptedClock(FakeClock):
    """A fake clock that runs each scheduled action when its wall instant is slept past."""

    def __init__(self) -> None:
        super().__init__()
        self._actions: list[tuple[float, Action]] = []

    def at(self, wall_s: float, action: Action) -> None:
        self._actions.append((wall_s, action))
        self._actions.sort(key=lambda scheduled: scheduled[0])

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(0)  # a real sleep lets other tasks run; so does this one
        target_s = self.now_s + seconds
        while self._actions and self._actions[0][0] <= target_s:
            wall_s, action = self._actions.pop(0)
            self.now_s = max(self.now_s, wall_s)
            await action()
        await super().sleep(target_s - self.now_s)


@dataclass(frozen=True)
class Sent:
    index: int
    event: Event
    wall_s: float


class MemoryStore:
    def __init__(self, clock: FakeClock, max_active: int = 10) -> None:
        self._clock = clock
        self._max_active = max_active
        self.states: dict[str, ReplayState] = {}
        self.streams: dict[str, list[Sent]] = {}
        self.leases: dict[str, str] = {}

    async def create(self, replay_id: str, state: ReplayState) -> bool:
        if len(self.states) >= self._max_active:
            return False
        self.states[replay_id] = state
        self.streams[replay_id] = []
        return True

    async def state(self, replay_id: str) -> ReplayState | None:
        return self.states.get(replay_id)

    async def update(
        self, replay_id: str, change: Callable[[ReplayState], ReplayState]
    ) -> ReplayState | None:
        if replay_id not in self.states:
            return None
        self.states[replay_id] = change(self.states[replay_id])
        return self.states[replay_id]

    async def sent(self, replay_id: str) -> int:
        return len(self.streams.get(replay_id, []))

    async def append(self, replay_id: str, first_index: int, events: Sequence[Event]) -> None:
        stream = self.streams[replay_id]
        assert first_index == len(stream), "an append must continue the stream exactly"
        now_s = self._clock()
        stream.extend(Sent(first_index + i, event, now_s) for i, event in enumerate(events))

    async def hold_lease(self, replay_id: str, owner: str, lease_s: float) -> bool:
        assert lease_s == POLICY.lease_s
        return self.leases.setdefault(replay_id, owner) == owner

    async def release_lease(self, replay_id: str, owner: str) -> None:
        if self.leases.get(replay_id) == owner:
            del self.leases[replay_id]

    def times(self, replay_id: str = REPLAY) -> list[tuple[int, float]]:
        return [(sent.index, sent.wall_s) for sent in self.streams[replay_id]]

    def events(self, replay_id: str = REPLAY) -> list[Event]:
        return [sent.event for sent in self.streams[replay_id]]


class MemoryRows:
    def __init__(self, sessions: dict[int, TimelineRows]) -> None:
        self._sessions = sessions

    async def is_loaded(self, session_key: int) -> bool:
        return session_key in self._sessions

    async def timeline_rows(self, session_key: int) -> TimelineRows | None:
        return self._sessions.get(session_key)


@dataclass
class World:
    clock: ScriptedClock
    store: MemoryStore
    rows: MemoryRows

    @property
    def produce(self) -> ProduceReplay:
        return ProduceReplay(self.rows, self.store, POLICY, self.clock, OWNER)

    @property
    def control(self) -> ControlReplay:
        return ControlReplay(self.store, self.clock)

    def speed_action(self, speed: ReplaySpeed) -> Action:
        return lambda: self.control.set_speed(REPLAY, speed)

    def begin(self, speed: ReplaySpeed, replay_id: str = REPLAY, session: int = SESSION) -> None:
        self.store.states[replay_id] = ReplayState(session, started(speed, self.clock()))
        self.store.streams[replay_id] = []


def world(sessions: dict[int, TimelineRows] | None = None, max_active: int = 10) -> World:
    clock = ScriptedClock()
    rows = MemoryRows({SESSION: positions_at(OFFSETS_S)} if sessions is None else sessions)
    return World(clock, MemoryStore(clock, max_active), rows)


async def test_at_1x_each_event_is_sent_when_its_session_time_comes() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)

    end = await w.produce(REPLAY)

    assert end is ReplayEnd.FINISHED
    assert w.store.times() == [(0, 1000.0), (1, 1001.5), (2, 1004.0), (3, 1010.0)]


async def test_at_10x_the_same_events_come_ten_times_faster() -> None:
    w = world()
    w.begin(ReplaySpeed.X10)

    await w.produce(REPLAY)

    assert w.store.times() == pytest.approx([(0, 1000.0), (1, 1000.15), (2, 1000.4), (3, 1001.0)])


async def test_events_due_in_one_tick_are_sent_together_in_order() -> None:
    w = world()
    w.begin(ReplaySpeed.X60)

    await w.produce(REPLAY)

    expected = timeline(positions_at(OFFSETS_S)).events
    assert w.store.events() == list(expected)
    assert [index for index, _ in w.store.times()] == [0, 1, 2, 3]


async def test_a_paused_replay_sends_nothing_until_it_resumes() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)
    w.clock.at(1002.0, lambda: w.control.pause(REPLAY))
    w.clock.at(1100.0, lambda: w.control.resume(REPLAY))

    await w.produce(REPLAY)

    assert w.store.times() == [(0, 1000.0), (1, 1001.5), (2, 1102.0), (3, 1108.0)]


async def test_a_new_speed_applies_from_the_session_time_it_was_set_at() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)
    w.clock.at(1002.0, lambda: w.control.set_speed(REPLAY, ReplaySpeed.X2))

    await w.produce(REPLAY)

    assert w.store.times() == [(0, 1000.0), (1, 1001.5), (2, 1003.0), (3, 1006.0)]


@pytest.mark.parametrize("seed", range(5))
async def test_pacing_never_changes_which_events_are_sent_or_their_order(seed: int) -> None:
    w = world({SESSION: clean_session(sample(RACE).raw())})
    w.begin(ReplaySpeed.X60)
    script = random.Random(seed)  # noqa: S311 - a test script, not a secret
    for step in range(20):
        wall_s = 1000.0 + step * script.uniform(1, 30)
        speed = script.choice(list(ReplaySpeed))
        w.clock.at(wall_s, w.speed_action(speed))
        w.clock.at(wall_s + 0.5, lambda: w.control.pause(REPLAY))
        w.clock.at(wall_s + 0.5 + script.uniform(0, 5), lambda: w.control.resume(REPLAY))
    w.clock.at(1700.0, lambda: w.control.set_speed(REPLAY, ReplaySpeed.X60))

    await w.produce(REPLAY)

    expected = timeline(clean_session(sample(RACE).raw())).events
    assert w.store.events() == list(expected)


async def test_a_restarted_producer_resumes_after_what_was_sent() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)
    first = asyncio.create_task(w.produce(REPLAY))
    await until(lambda: len(w.store.streams[REPLAY]) == 3)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    end = await w.produce(REPLAY)

    assert end is ReplayEnd.FINISHED
    assert w.store.events() == list(timeline(positions_at(OFFSETS_S)).events)
    assert REPLAY not in w.store.leases


async def test_a_replay_another_producer_holds_is_left_alone() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)
    w.store.leases[REPLAY] = "other-process"

    end = await w.produce(REPLAY)

    assert end is ReplayEnd.BUSY
    assert w.store.times() == []
    assert w.store.leases[REPLAY] == "other-process"


async def test_a_producer_that_loses_its_lease_stops_sending() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)

    def steal() -> Awaitable[None]:
        w.store.leases[REPLAY] = "other-process"
        return asyncio.sleep(0)

    w.clock.at(1002.0, steal)

    end = await w.produce(REPLAY)

    assert end is ReplayEnd.LEASE_LOST
    assert w.store.times() == [(0, 1000.0), (1, 1001.5)]
    assert w.store.leases[REPLAY] == "other-process"


async def test_a_replay_that_expires_stops_its_producer() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)

    def expire() -> Awaitable[None]:
        del w.store.states[REPLAY]
        return asyncio.sleep(0)

    w.clock.at(1002.0, expire)

    end = await w.produce(REPLAY)

    assert end is ReplayEnd.EXPIRED
    assert w.store.times() == [(0, 1000.0), (1, 1001.5)]


async def test_a_replay_gone_before_its_producer_starts_is_expired() -> None:
    w = world()

    assert await w.produce(REPLAY) is ReplayEnd.EXPIRED
    assert REPLAY not in w.store.leases


async def test_a_failed_replay_is_not_produced_again() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)
    w.store.states[REPLAY] = ReplayState(SESSION, started(ReplaySpeed.X1, 1000.0), "boom")

    assert await w.produce(REPLAY) is ReplayEnd.FAILED
    assert w.store.times() == []


async def test_an_empty_session_finishes_without_sending() -> None:
    w = world({SESSION: Rows()})
    w.begin(ReplaySpeed.X1)

    assert await w.produce(REPLAY) is ReplayEnd.FINISHED
    assert w.store.times() == []


async def test_controls_report_the_new_state() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)
    w.clock.now_s = 1004.0

    assert await w.control.pause(REPLAY) == ReplayState(SESSION, Paused(ReplaySpeed.X1, 4.0))
    assert await w.control.set_speed(REPLAY, ReplaySpeed.X5) == ReplayState(
        SESSION, Paused(ReplaySpeed.X5, 4.0)
    )
    assert await w.control.resume(REPLAY) == ReplayState(
        SESSION, Playing(ReplaySpeed.X5, 4.0, 1004.0)
    )


@pytest.mark.parametrize("control", ["pause", "resume", "set_speed"])
async def test_a_control_of_an_unknown_replay_fails(control: str) -> None:
    w = world()
    calls = {
        "pause": lambda: w.control.pause("missing"),
        "resume": lambda: w.control.resume("missing"),
        "set_speed": lambda: w.control.set_speed("missing", ReplaySpeed.X2),
    }

    with pytest.raises(ReplayNotFoundError, match="missing"):
        await calls[control]()

    assert w.store.states == {}


async def test_starting_a_replay_stores_it_and_produces_it() -> None:
    w = world()
    producers = ReplayProducers(w.produce, w.store)
    start = StartReplay(w.rows, w.store, producers, w.clock, lambda: REPLAY)

    replay_id = await start(SESSION, ReplaySpeed.X60)
    await until(lambda: len(w.store.streams[REPLAY]) == len(OFFSETS_S))

    assert replay_id == REPLAY
    assert w.store.states[REPLAY] == ReplayState(SESSION, Playing(ReplaySpeed.X60, 0.0, 1000.0))
    assert w.store.events() == list(timeline(positions_at(OFFSETS_S)).events)
    await producers.aclose()


async def test_a_session_not_in_the_clean_model_cannot_be_replayed() -> None:
    w = world()
    producers = ReplayProducers(w.produce, w.store)
    start = StartReplay(w.rows, w.store, producers, w.clock, lambda: REPLAY)

    with pytest.raises(SessionNotLoadedError, match=str(OTHER_SESSION)):
        await start(OTHER_SESSION, ReplaySpeed.X1)

    assert w.store.states == {}


async def test_a_replay_over_the_limit_is_refused() -> None:
    w = world(max_active=1)
    w.begin(ReplaySpeed.X1, replay_id="already-running")
    producers = ReplayProducers(w.produce, w.store)
    start = StartReplay(w.rows, w.store, producers, w.clock, lambda: REPLAY)

    with pytest.raises(TooManyReplaysError):
        await start(SESSION, ReplaySpeed.X1)

    assert set(w.store.states) == {"already-running"}
    await producers.aclose()


async def test_a_failing_replay_records_its_failure_and_spares_the_others() -> None:
    w = world()
    w.begin(ReplaySpeed.X60, replay_id="broken", session=OTHER_SESSION)
    w.begin(ReplaySpeed.X60)
    producers = ReplayProducers(w.produce, w.store)

    producers.ensure("broken")
    producers.ensure(REPLAY)
    await until(lambda: w.store.states["broken"].failure is not None)
    await until(lambda: len(w.store.streams[REPLAY]) == len(OFFSETS_S))

    failure = f"SessionNotLoadedError: session {OTHER_SESSION} is not in the clean model"
    assert w.store.states["broken"].failure == failure
    assert w.store.events() == list(timeline(positions_at(OFFSETS_S)).events)
    await producers.aclose()


async def test_a_replay_has_one_producer_in_a_process() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)
    producers = ReplayProducers(w.produce, w.store)

    producers.ensure(REPLAY)
    producers.ensure(REPLAY)
    await until(lambda: len(w.store.streams[REPLAY]) == len(OFFSETS_S))

    assert w.store.times() == [(0, 1000.0), (1, 1001.5), (2, 1004.0), (3, 1010.0)]
    assert w.store.states[REPLAY].failure is None
    await producers.aclose()


async def test_closing_the_producers_stops_them_and_frees_their_leases() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)
    producers = ReplayProducers(w.produce, w.store)
    producers.ensure(REPLAY)
    await until(lambda: len(w.store.streams[REPLAY]) == 1)

    await producers.aclose()

    assert w.store.leases == {}
    assert w.store.times() == [(0, 1000.0)]


@pytest.mark.parametrize(("tick_s", "lease_s"), [(0.0, 5.0), (-1.0, 5.0), (5.0, 5.0), (6.0, 5.0)])
def test_a_tick_must_be_positive_and_shorter_than_the_lease(tick_s: float, lease_s: float) -> None:
    with pytest.raises(ValueError, match="tick_s"):
        ReplayPolicy(tick_s=tick_s, lease_s=lease_s)
