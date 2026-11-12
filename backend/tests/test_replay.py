import asyncio
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

from f1_strategy.application.replay import (
    AppendOutcome,
    ControlReplay,
    LapNotFoundError,
    ProduceReplay,
    ReplayEnd,
    ReplayFailedError,
    ReplayFailure,
    ReplayNotFoundError,
    ReplayPolicy,
    ReplayProducers,
    ReplayReset,
    ReplayState,
    ReplayStatus,
    SeekReplay,
    SessionNotLoadedError,
    StartReplay,
    StreamEntry,
    StreamRead,
    TooManyReplaysError,
    WatchReplay,
)
from f1_strategy.domain.clean import Lap, Position, clean_session
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
POLICY = ReplayPolicy(tick_s=0.25, lease_s=5.0, append_batch=100)
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


def lap_started(lap_number: int, offset_s: float) -> Lap:
    """A lap with a start and no end: it moves no event, only where the lap starts."""
    return Lap(
        SESSION, 1, lap_number, T0 + timedelta(seconds=offset_s), None,
        None, None, None, None, None, None, is_pit_out_lap=False,
    )  # fmt: skip


def with_laps(rows: Rows, starts_s: dict[int, float]) -> Rows:
    rows.laps = [lap_started(lap_number, offset_s) for lap_number, offset_s in starts_s.items()]
    return rows


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
    """`streams` holds the latest generation of each replay; `resets` the reset it starts with.
    With `expire_after_sent`, a replay's state expires once its stream holds that many events,
    leaving the stream to read."""

    def __init__(self, clock: FakeClock, max_active: int = 10) -> None:
        self._clock = clock
        self._max_active = max_active
        self.states: dict[str, ReplayState] = {}
        self.streams: dict[str, list[Sent]] = {}
        self.resets: dict[str, ReplayReset] = {}
        self.leases: dict[str, str] = {}
        self.reads = 0
        self.expire_after_sent: int | None = None
        self.append_sizes: list[int] = []

    async def create(self, replay_id: str, state: ReplayState) -> bool:
        if len(self.states) >= self._max_active:
            return False
        self.states[replay_id] = state
        self.streams[replay_id] = []
        return True

    async def state(self, replay_id: str) -> ReplayState | None:
        if len(self.streams.get(replay_id, [])) == self.expire_after_sent:
            self.states.pop(replay_id, None)
        return self.states.get(replay_id)

    async def update(
        self, replay_id: str, change: Callable[[ReplayState], ReplayState]
    ) -> ReplayState | None:
        if replay_id not in self.states:
            return None
        self.states[replay_id] = change(self.states[replay_id])
        return self.states[replay_id]

    async def seek(
        self,
        replay_id: str,
        change: Callable[[ReplayState], ReplayState],
        lap_number: int,
        caught_up: Sequence[tuple[int, Event]],
    ) -> ReplayState | None:
        if replay_id not in self.states:
            return None
        changed = change(self.states[replay_id])
        self.states[replay_id] = changed
        now_s = self._clock()
        self.streams[replay_id] = [Sent(index, event, now_s) for index, event in caught_up]
        self.resets[replay_id] = ReplayReset(
            f"{changed.generation}-0", lap_number, changed.playback.session_s
        )
        return changed

    async def sent(self, replay_id: str) -> int:
        stream = self.streams.get(replay_id, [])
        return stream[-1].index + 1 if stream else 0

    async def append(
        self, replay_id: str, generation: int, first_index: int, events: Sequence[Event]
    ) -> AppendOutcome:
        if replay_id not in self.states:
            return AppendOutcome.GONE
        if generation < self.states[replay_id].generation:
            return AppendOutcome.SUPERSEDED
        stream = self.streams[replay_id]
        assert first_index == await self.sent(replay_id), "an append must continue the stream"
        now_s = self._clock()
        stream.extend(Sent(first_index + i, event, now_s) for i, event in enumerate(events))
        self.append_sizes.append(len(events))
        return AppendOutcome.APPENDED

    async def delete(self, replay_id: str) -> bool:
        self.streams.pop(replay_id, None)
        self.resets.pop(replay_id, None)
        self.leases.pop(replay_id, None)
        return self.states.pop(replay_id, None) is not None

    async def read(self, replay_id: str, after: str | None, block_s: float) -> StreamRead | None:
        assert block_s == POLICY.tick_s
        if replay_id not in self.states:
            return None
        generation = self.states[replay_id].generation
        stream: list[StreamEntry | ReplayReset] = [
            StreamEntry(f"{generation}-{sent.index + 1}", sent.event.kind, str(sent.index))
            for sent in self.streams[replay_id]
        ]
        if replay_id in self.resets:
            stream.insert(0, self.resets[replay_id])
        entries = tuple(item for item in stream if after is None or _id(item) > _id_of(after))
        if not entries:
            await asyncio.sleep(0)
        self.reads += 1
        return StreamRead(self.states[replay_id], entries)

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


def _id(item: StreamEntry | ReplayReset) -> tuple[int, int]:
    return _id_of(item.entry_id)


def _id_of(entry_id: str) -> tuple[int, int]:
    generation, n = entry_id.split("-")
    return int(generation), int(n)


class StoppedBeforeAppend(MemoryStore):
    """Stops the replay right after the producer's first read of it inside its loop, so its
    next append finds the replay gone."""

    def __init__(self, clock: FakeClock) -> None:
        super().__init__(clock)
        self.state_reads = 0

    async def state(self, replay_id: str) -> ReplayState | None:
        read = await super().state(replay_id)
        self.state_reads += 1
        if self.state_reads == 2:
            await self.delete(replay_id)
        return read


class SoughtBeforeAppend(MemoryStore):
    """Seeks the replay to lap 2 right after the producer's first read of it inside its loop,
    so its next append is of a generation the seek replaced."""

    def __init__(self, clock: FakeClock) -> None:
        super().__init__(clock)
        self.state_reads = 0

    async def state(self, replay_id: str) -> ReplayState | None:
        read = await super().state(replay_id)
        self.state_reads += 1
        if self.state_reads == 2:
            await self.seek(
                replay_id,
                lambda state: replace(
                    state, generation=1, playback=Playing(ReplaySpeed.X60, 4.0, self._clock())
                ),
                2,
                [],
            )
        return read


class MemoryRows:
    def __init__(self, sessions: dict[int, TimelineRows]) -> None:
        self._sessions = sessions

    async def is_loaded(self, session_key: int) -> bool:
        return session_key in self._sessions

    async def timeline_rows(self, session_key: int) -> TimelineRows | None:
        return self._sessions.get(session_key)


class ExpiringWhileRead(MemoryRows):
    """Expires the replay while its session's rows are read."""

    def __init__(self, store: MemoryStore, sessions: dict[int, TimelineRows]) -> None:
        super().__init__(sessions)
        self._store = store

    async def timeline_rows(self, session_key: int) -> TimelineRows | None:
        self._store.states.pop(REPLAY, None)
        return await super().timeline_rows(session_key)


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

    def seek(self, producers: ReplayProducers | None = None) -> SeekReplay:
        return SeekReplay(
            self.rows,
            self.store,
            producers or ReplayProducers(self.produce, self.store),
            self.clock,
        )

    async def produce_whole(self) -> ReplayEnd:
        """Produces the replay until it has sent its whole timeline, then lets it expire."""
        rows = await self.rows.timeline_rows(SESSION)
        assert rows is not None
        self.store.expire_after_sent = len(timeline(rows).events)
        return await self.produce(REPLAY)

    def expire_at(self, wall_s: float) -> None:
        async def expire() -> None:
            self.store.states.pop(REPLAY, None)

        self.clock.at(wall_s, expire)

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

    end = await w.produce_whole()

    assert end is ReplayEnd.EXPIRED
    assert w.store.times() == [(0, 1000.0), (1, 1001.5), (2, 1004.0), (3, 1010.0)]


async def test_at_10x_the_same_events_come_ten_times_faster() -> None:
    w = world()
    w.begin(ReplaySpeed.X10)

    await w.produce_whole()

    assert w.store.times() == pytest.approx([(0, 1000.0), (1, 1000.15), (2, 1000.4), (3, 1001.0)])


async def test_events_due_in_one_tick_are_sent_together_in_order() -> None:
    w = world()
    w.begin(ReplaySpeed.X60)

    await w.produce_whole()

    expected = timeline(positions_at(OFFSETS_S)).events
    assert w.store.events() == list(expected)
    assert [index for index, _ in w.store.times()] == [0, 1, 2, 3]


async def test_a_paused_replay_sends_nothing_until_it_resumes() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)
    w.clock.at(1002.0, lambda: w.control.pause(REPLAY))
    w.clock.at(1100.0, lambda: w.control.resume(REPLAY))

    await w.produce_whole()

    assert w.store.times() == [(0, 1000.0), (1, 1001.5), (2, 1102.0), (3, 1108.0)]


async def test_a_new_speed_applies_from_the_session_time_it_was_set_at() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)
    w.clock.at(1002.0, lambda: w.control.set_speed(REPLAY, ReplaySpeed.X2))

    await w.produce_whole()

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

    await w.produce_whole()

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

    end = await w.produce_whole()

    assert end is ReplayEnd.EXPIRED
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


async def test_a_replay_stopped_just_before_an_append_ends_its_producer() -> None:
    clock = ScriptedClock()
    w = World(clock, StoppedBeforeAppend(clock), MemoryRows({SESSION: positions_at(OFFSETS_S)}))
    w.begin(ReplaySpeed.X1)

    end = await w.produce(REPLAY)

    assert end is ReplayEnd.EXPIRED
    assert w.store.streams == {}
    assert w.store.leases == {}


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


async def test_an_empty_session_sends_nothing_until_it_expires() -> None:
    w = world({SESSION: Rows()})
    w.begin(ReplaySpeed.X1)
    w.expire_at(1060.0)

    assert await w.produce(REPLAY) is ReplayEnd.EXPIRED
    assert w.store.times() == []
    assert w.clock.now_s >= 1060.0


async def test_a_replay_at_its_end_keeps_its_producer_and_sends_nothing_more() -> None:
    w = world()
    w.begin(ReplaySpeed.X60)
    producing = asyncio.create_task(w.produce(REPLAY))

    await until(lambda: w.clock.now_s > 1100.0)

    assert not producing.done()
    assert w.store.leases[REPLAY] == OWNER
    assert w.store.events() == list(timeline(positions_at(OFFSETS_S)).events)
    producing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await producing


async def test_controls_report_the_new_state_and_session_time() -> None:
    w = world()
    w.begin(ReplaySpeed.X1)
    w.clock.now_s = 1004.0

    paused_status = await w.control.pause(REPLAY)
    faster = await w.control.set_speed(REPLAY, ReplaySpeed.X5)
    resumed_status = await w.control.resume(REPLAY)
    w.clock.now_s = 1006.0
    later = await w.control.status(REPLAY)

    assert paused_status == ReplayStatus(ReplayState(SESSION, Paused(ReplaySpeed.X1, 4.0)), 4.0)
    assert faster == ReplayStatus(ReplayState(SESSION, Paused(ReplaySpeed.X5, 4.0)), 4.0)
    assert resumed_status == ReplayStatus(
        ReplayState(SESSION, Playing(ReplaySpeed.X5, 4.0, 1004.0)), 4.0
    )
    assert later == ReplayStatus(ReplayState(SESSION, Playing(ReplaySpeed.X5, 4.0, 1004.0)), 14.0)


async def test_stopping_a_replay_removes_it_and_frees_its_place() -> None:
    w = world(max_active=1)
    w.begin(ReplaySpeed.X1)
    w.store.leases[REPLAY] = OWNER

    await w.control.stop(REPLAY)

    assert (w.store.states, w.store.streams, w.store.leases) == ({}, {}, {})
    assert await w.store.create("replay-2", ReplayState(SESSION, started(ReplaySpeed.X1, 0.0)))
    with pytest.raises(
        ReplayNotFoundError, match=f"^replay {REPLAY} does not exist or has expired$"
    ):
        await w.control.status(REPLAY)


@pytest.mark.parametrize("control", ["pause", "resume", "set_speed", "status", "stop", "seek"])
async def test_a_control_of_an_unknown_replay_fails(control: str) -> None:
    w = world()
    calls: dict[str, Callable[[], Awaitable[object]]] = {
        "pause": lambda: w.control.pause("missing"),
        "resume": lambda: w.control.resume("missing"),
        "set_speed": lambda: w.control.set_speed("missing", ReplaySpeed.X2),
        "status": lambda: w.control.status("missing"),
        "stop": lambda: w.control.stop("missing"),
        "seek": lambda: w.seek()("missing", 1),
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


async def test_events_due_together_are_appended_in_pieces_of_the_batch_cap() -> None:
    w = world()
    w.store.states[REPLAY] = ReplayState(SESSION, Paused(ReplaySpeed.X1, 10.0))
    w.store.streams[REPLAY] = []
    w.store.expire_after_sent = len(OFFSETS_S)
    policy = replace(POLICY, append_batch=3)

    end = await ProduceReplay(w.rows, w.store, policy, w.clock, OWNER)(REPLAY)

    assert end is ReplayEnd.EXPIRED
    assert w.store.append_sizes == [3, 1]
    assert w.store.times() == [(0, 1000.0), (1, 1000.0), (2, 1000.0), (3, 1000.0)]
    assert w.store.events() == list(timeline(positions_at(OFFSETS_S)).events)


@pytest.mark.parametrize("append_batch", [0, -1])
def test_an_append_batch_must_hold_at_least_one_event(append_batch: int) -> None:
    with pytest.raises(ValueError, match="append_batch must be at least 1"):
        ReplayPolicy(tick_s=0.25, lease_s=5.0, append_batch=append_batch)


@pytest.mark.parametrize(("tick_s", "lease_s"), [(0.0, 5.0), (-1.0, 5.0), (5.0, 5.0), (6.0, 5.0)])
def test_a_tick_must_be_positive_and_shorter_than_the_lease(tick_s: float, lease_s: float) -> None:
    with pytest.raises(ValueError, match="tick_s"):
        ReplayPolicy(tick_s=tick_s, lease_s=lease_s, append_batch=1)


async def watched(
    w: World, producers: ReplayProducers, after: str | None, count: int
) -> list[StreamEntry | ReplayReset | ReplayFailure]:
    entries = await WatchReplay(w.store, producers, POLICY)(REPLAY, after)
    received: list[StreamEntry | ReplayReset | ReplayFailure] = []
    async for entry in entries:
        received.append(entry)
        if len(received) == count:
            break
    return received


def entry(index: int, generation: int = 0) -> StreamEntry:
    kind = timeline(positions_at(OFFSETS_S)).events[index].kind
    return StreamEntry(f"{generation}-{index + 1}", kind, str(index))


async def test_watching_a_replay_starts_its_producer_and_receives_every_event() -> None:
    w = world()
    w.begin(ReplaySpeed.X60)
    producers = ReplayProducers(w.produce, w.store)

    received = await watched(w, producers, None, len(OFFSETS_S))

    assert received == [entry(index) for index in range(len(OFFSETS_S))]
    await producers.aclose()


async def test_watching_again_resumes_after_the_last_entry_seen() -> None:
    w = world()
    w.begin(ReplaySpeed.X60)
    producers = ReplayProducers(w.produce, w.store)

    received = await watched(w, producers, "0-2", 2)

    assert received == [entry(2), entry(3)]
    await producers.aclose()


async def test_a_failed_replay_ends_its_watch_with_the_failure() -> None:
    w = world()
    w.store.states[REPLAY] = ReplayState(SESSION, started(ReplaySpeed.X60, 1000.0), "boom")
    w.store.streams[REPLAY] = []
    producers = ReplayProducers(w.produce, w.store)

    received = await watched(w, producers, None, 10)

    assert received == [ReplayFailure("boom")]
    await producers.aclose()


async def test_a_watch_ends_when_its_replay_expires() -> None:
    w = world()
    w.begin(ReplaySpeed.X60)
    producers = ReplayProducers(w.produce, w.store)
    entries = await WatchReplay(w.store, producers, POLICY)(REPLAY, None)
    received = [await anext(entries)]

    del w.store.states[REPLAY]

    received.extend([item async for item in entries])
    assert received[0] == entry(0)
    assert all(isinstance(item, StreamEntry) for item in received)
    await producers.aclose()


async def test_watching_an_unknown_replay_fails_before_any_read() -> None:
    w = world()
    producers = ReplayProducers(w.produce, w.store)

    with pytest.raises(ReplayNotFoundError, match="missing"):
        await WatchReplay(w.store, producers, POLICY)("missing", None)

    assert w.store.reads == 0
    assert w.store.leases == {}


LAP_2_S = 4.0


def lapped_world() -> World:
    return world({SESSION: with_laps(positions_at(OFFSETS_S), {1: 0.0, 2: LAP_2_S})})


async def test_a_seek_sends_the_session_up_to_the_lap_at_once_then_plays_on() -> None:
    w = lapped_world()
    w.begin(ReplaySpeed.X1)
    producers = ReplayProducers(w.produce, w.store)
    w.clock.at(1012.0, lambda: w.seek(producers)(REPLAY, 2))

    producers.ensure(REPLAY)
    await until(
        lambda: w.store.states[REPLAY].generation == 1 and len(w.store.streams[REPLAY]) == 4
    )

    assert w.store.resets[REPLAY] == ReplayReset("1-0", 2, LAP_2_S)
    assert w.store.times() == [(0, 1012.0), (1, 1012.0), (2, 1012.0), (3, 1018.0)]
    assert w.store.events() == list(timeline(positions_at(OFFSETS_S)).events)
    await producers.aclose()


def one_driver_at(offsets_s: Sequence[float]) -> Rows:
    return Rows(
        positions=[
            Position(SESSION, 1, T0 + timedelta(seconds=offset_s), 1) for offset_s in offsets_s
        ]
    )


async def test_a_seek_sends_only_what_is_still_current_at_the_lap_then_plays_on() -> None:
    w = world({SESSION: with_laps(one_driver_at(OFFSETS_S), {2: LAP_2_S})})
    w.begin(ReplaySpeed.X1)
    producers = ReplayProducers(w.produce, w.store)
    w.clock.at(1012.0, lambda: w.seek(producers)(REPLAY, 2))

    producers.ensure(REPLAY)
    await until(lambda: w.store.states[REPLAY].generation == 1 and w.clock.now_s >= 1018.0)

    events = timeline(one_driver_at(OFFSETS_S)).events
    assert w.store.times() == [(2, 1012.0), (3, 1018.0)]
    assert w.store.events() == [events[2], events[3]]
    await producers.aclose()


async def test_a_seek_while_paused_rebuilds_up_to_the_lap_and_stays_paused() -> None:
    w = lapped_world()
    w.begin(ReplaySpeed.X1)
    producers = ReplayProducers(w.produce, w.store)
    w.clock.at(1002.0, lambda: w.control.pause(REPLAY))
    w.clock.at(1005.0, lambda: w.seek(producers)(REPLAY, 2))

    producers.ensure(REPLAY)
    await until(lambda: w.clock.now_s > 1050.0)

    assert w.store.states[REPLAY].playback == Paused(ReplaySpeed.X1, LAP_2_S)
    assert w.store.times() == [(0, 1005.0), (1, 1005.0), (2, 1005.0)]
    await producers.aclose()


async def test_a_seek_reports_the_new_state_and_starts_a_producer() -> None:
    w = lapped_world()
    w.begin(ReplaySpeed.X5)
    w.clock.now_s = 1030.0
    producers = ReplayProducers(w.produce, w.store)

    status = await w.seek(producers)(REPLAY, 1)
    await until(lambda: REPLAY in w.store.leases)

    sought_state = ReplayState(SESSION, Playing(ReplaySpeed.X5, 0.0, 1030.0), generation=1)
    assert status == ReplayStatus(sought_state, 0.0)
    assert w.store.leases[REPLAY] == OWNER
    await producers.aclose()


async def test_a_failed_replay_is_not_sought() -> None:
    w = lapped_world()
    failed = ReplayState(SESSION, started(ReplaySpeed.X1, 1000.0), "boom")
    w.store.states[REPLAY] = failed
    w.store.streams[REPLAY] = []

    with pytest.raises(ReplayFailedError, match=f"^replay {REPLAY} failed and cannot move: boom$"):
        await w.seek()(REPLAY, 2)

    assert w.store.states[REPLAY] == failed
    assert w.store.resets == {}


async def test_a_lap_no_driver_started_is_not_sought() -> None:
    w = lapped_world()
    w.begin(ReplaySpeed.X1)
    before = w.store.states[REPLAY]

    with pytest.raises(LapNotFoundError, match=f"^session {SESSION} has no start for lap 9$"):
        await w.seek()(REPLAY, 9)

    assert w.store.states[REPLAY] == before
    assert w.store.resets == {}


async def test_a_replay_that_expires_while_its_seek_reads_the_session_is_not_found() -> None:
    clock = ScriptedClock()
    store = MemoryStore(clock)
    rows = ExpiringWhileRead(store, {SESSION: with_laps(positions_at(OFFSETS_S), {2: LAP_2_S})})
    w = World(clock, store, rows)
    w.begin(ReplaySpeed.X1)
    producers = ReplayProducers(w.produce, w.store)

    with pytest.raises(ReplayNotFoundError, match=REPLAY):
        await w.seek(producers)(REPLAY, 2)

    assert w.store.resets == {}
    assert w.store.leases == {}


async def test_an_append_a_seek_superseded_reaches_nothing_and_the_new_generation_follows() -> None:
    clock = ScriptedClock()
    store = SoughtBeforeAppend(clock)
    w = World(clock, store, MemoryRows({SESSION: positions_at(OFFSETS_S)}))
    w.begin(ReplaySpeed.X60)
    store.expire_after_sent = len(OFFSETS_S)

    end = await w.produce(REPLAY)

    assert end is ReplayEnd.EXPIRED
    assert w.store.times() == [(0, 1000.0), (1, 1000.0), (2, 1000.0), (3, 1000.1)]
    assert w.store.events() == list(timeline(positions_at(OFFSETS_S)).events)


async def test_watching_after_a_seek_receives_the_reset_then_the_new_generation() -> None:
    w = lapped_world()
    w.begin(ReplaySpeed.X60)
    producers = ReplayProducers(w.produce, w.store)
    producers.ensure(REPLAY)
    await until(lambda: len(w.store.streams[REPLAY]) == len(OFFSETS_S))

    await w.seek(producers)(REPLAY, 2)
    received = await watched(w, producers, "0-4", 4)

    assert received == [
        ReplayReset("1-0", 2, LAP_2_S),
        entry(0, generation=1),
        entry(1, generation=1),
        entry(2, generation=1),
    ]
    await producers.aclose()
