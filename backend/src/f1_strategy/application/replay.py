"""Replays: start, control and produce a paced copy of a session's timeline (ADR 0009).

The content of a replay is its session's timeline; pacing only decides when each event is
appended. What was appended is the progress: a producer that starts again resumes after it.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from f1_strategy.domain.playback import (
    Paused,
    Playback,
    ReplaySpeed,
    due_until,
    offsets_s,
    paused,
    resumed,
    session_s_at,
    started,
    wall_s_due,
    with_speed,
)
from f1_strategy.domain.replay import Event, EventKind, Timeline, TimelineRows, timeline


class SessionNotLoadedError(LookupError):
    pass


class ReplayNotFoundError(LookupError):
    pass


class TooManyReplaysError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReplayState:
    session_key: int
    playback: Playback
    failure: str | None = None


@dataclass(frozen=True)
class ReplayStatus:
    """A replay as its viewer sees it now: its state and where in its session it is."""

    state: ReplayState
    session_s: float


@dataclass(frozen=True)
class StreamEntry:
    """One event as its viewers receive it: the stream's id for it, its kind, and its encoding."""

    entry_id: str
    kind: EventKind
    data: str


@dataclass(frozen=True)
class StreamRead:
    state: ReplayState
    entries: tuple[StreamEntry, ...]


@dataclass(frozen=True)
class ReplayFailure:
    message: str


class ReplayRows(Protocol):
    async def is_loaded(self, session_key: int) -> bool: ...

    async def timeline_rows(self, session_key: int) -> TimelineRows | None: ...


class ReplayStore(Protocol):
    async def create(self, replay_id: str, state: ReplayState) -> bool:
        """Store a new replay unless the configured number of replays is active; False when
        refused."""
        ...

    async def state(self, replay_id: str) -> ReplayState | None: ...

    async def update(
        self, replay_id: str, change: Callable[[ReplayState], ReplayState]
    ) -> ReplayState | None:
        """Apply `change` atomically; None when the replay does not exist."""
        ...

    async def sent(self, replay_id: str) -> int:
        """How many events of the timeline the replay's stream holds."""
        ...

    async def append(self, replay_id: str, first_index: int, events: Sequence[Event]) -> None: ...

    async def read(self, replay_id: str, after: str | None, block_s: float) -> StreamRead | None:
        """The entries after the id `after` (from the start when None), waiting up to `block_s`
        for one; a read keeps the replay from expiring. None when the replay does not exist."""
        ...

    async def hold_lease(self, replay_id: str, owner: str, lease_s: float) -> bool:
        """Take or renew the producer lease; False when another owner holds it."""
        ...

    async def release_lease(self, replay_id: str, owner: str) -> None: ...


class WallClock(Protocol):
    def __call__(self) -> float:
        """Seconds since the epoch."""
        ...

    async def sleep(self, seconds: float) -> None: ...


@dataclass(frozen=True)
class ReplayPolicy:
    tick_s: float
    lease_s: float

    def __post_init__(self) -> None:
        if not 0 < self.tick_s < self.lease_s:
            raise ValueError(
                f"tick_s must be positive and shorter than lease_s, got {self.tick_s}"
                f" and {self.lease_s}"
            )


class ReplayEnd(StrEnum):
    FINISHED = "finished"
    EXPIRED = "expired"
    BUSY = "busy"
    LEASE_LOST = "lease_lost"
    FAILED = "failed"


class ControlReplay:
    def __init__(self, store: ReplayStore, clock: WallClock) -> None:
        self._store = store
        self._clock = clock

    async def status(self, replay_id: str) -> ReplayStatus:
        state = await self._store.state(replay_id)
        if state is None:
            raise ReplayNotFoundError(f"replay {replay_id} does not exist or has expired")
        return self._status(state, self._clock())

    async def pause(self, replay_id: str) -> ReplayStatus:
        now = self._clock()
        return await self._change(replay_id, now, lambda playback: paused(playback, now))

    async def resume(self, replay_id: str) -> ReplayStatus:
        now = self._clock()
        return await self._change(replay_id, now, lambda playback: resumed(playback, now))

    async def set_speed(self, replay_id: str, speed: ReplaySpeed) -> ReplayStatus:
        now = self._clock()
        return await self._change(replay_id, now, lambda playback: with_speed(playback, speed, now))

    async def _change(
        self, replay_id: str, now: float, change: Callable[[Playback], Playback]
    ) -> ReplayStatus:
        state = await self._store.update(
            replay_id, lambda state: replace(state, playback=change(state.playback))
        )
        if state is None:
            raise ReplayNotFoundError(f"replay {replay_id} does not exist or has expired")
        return self._status(state, now)

    @staticmethod
    def _status(state: ReplayState, now: float) -> ReplayStatus:
        return ReplayStatus(state, session_s_at(state.playback, now))


class ProduceReplay:
    """Appends a replay's events as they fall due, until the timeline ends or the replay is
    gone. One producer per replay at a time, held by a lease that each tick renews."""

    def __init__(
        self,
        rows: ReplayRows,
        store: ReplayStore,
        policy: ReplayPolicy,
        clock: WallClock,
        owner: str,
    ) -> None:
        self._rows = rows
        self._store = store
        self._policy = policy
        self._clock = clock
        self._owner = owner

    async def __call__(self, replay_id: str) -> ReplayEnd:
        if not await self._hold(replay_id):
            return ReplayEnd.BUSY
        try:
            return await self._produce(replay_id)
        finally:
            await self._store.release_lease(replay_id, self._owner)

    async def _produce(self, replay_id: str) -> ReplayEnd:
        state = await self._store.state(replay_id)
        if state is None:
            return ReplayEnd.EXPIRED
        if state.failure is not None:
            return ReplayEnd.FAILED
        built = await self._timeline(state.session_key)
        offsets = offsets_s(built)
        sent = await self._store.sent(replay_id)
        while sent < len(built.events):
            if not await self._hold(replay_id):
                return ReplayEnd.LEASE_LOST
            state = await self._store.state(replay_id)
            if state is None:
                return ReplayEnd.EXPIRED
            now = self._clock()
            due = due_until(state.playback, offsets, sent, now)
            if due > sent:
                await self._store.append(replay_id, sent, built.events[sent:due])
                sent = due
            if sent < len(built.events):
                await self._clock.sleep(self._wait_s(state.playback, offsets[sent], now))
        return ReplayEnd.FINISHED

    async def _timeline(self, session_key: int) -> Timeline:
        rows = await self._rows.timeline_rows(session_key)
        if rows is None:
            raise SessionNotLoadedError(f"session {session_key} is not in the clean model")
        # About 50 ms of CPU for a race's 30,000 events (measured 2026-11-04); a thread keeps
        # every other replay's stream moving meanwhile.
        return await asyncio.to_thread(timeline, rows)

    def _wait_s(self, playback: Playback, next_session_s: float, now: float) -> float:
        if isinstance(playback, Paused):
            return self._policy.tick_s
        return min(self._policy.tick_s, max(0.0, wall_s_due(playback, next_session_s) - now))

    async def _hold(self, replay_id: str) -> bool:
        return await self._store.hold_lease(replay_id, self._owner, self._policy.lease_s)


class ReplayProducers:
    """The producer tasks of this process, at most one per replay, so they are bounded by the
    number of replays the store accepts. Closing cancels and awaits every one."""

    def __init__(self, produce: ProduceReplay, store: ReplayStore) -> None:
        self._produce = produce
        self._store = store
        self._tasks: dict[str, asyncio.Task[ReplayEnd]] = {}

    def ensure(self, replay_id: str) -> None:
        if replay_id in self._tasks:
            return
        task = asyncio.create_task(self._run(replay_id))
        self._tasks[replay_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(replay_id, None))

    async def aclose(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, replay_id: str) -> ReplayEnd:
        try:
            return await self._produce(replay_id)
        # One replay's failure is recorded on that replay, where its viewer reads it, and the
        # other replays keep running.
        except Exception as error:  # noqa: BLE001 - recorded on the replay, not swallowed
            failure = f"{type(error).__name__}: {error}"
            await self._store.update(replay_id, lambda state: replace(state, failure=failure))
            return ReplayEnd.FAILED


class StartReplay:
    def __init__(
        self,
        rows: ReplayRows,
        store: ReplayStore,
        producers: ReplayProducers,
        clock: WallClock,
        new_id: Callable[[], str],
    ) -> None:
        self._rows = rows
        self._store = store
        self._producers = producers
        self._clock = clock
        self._new_id = new_id

    async def __call__(self, session_key: int, speed: ReplaySpeed) -> str:
        if not await self._rows.is_loaded(session_key):
            raise SessionNotLoadedError(f"session {session_key} is not in the clean model")
        replay_id = self._new_id()
        state = ReplayState(session_key, started(speed, self._clock()))
        if not await self._store.create(replay_id, state):
            raise TooManyReplaysError("the number of active replays is at its limit")
        self._producers.ensure(replay_id)
        return replay_id


class WatchReplay:
    """A viewer's read of a replay: from where the viewer stopped, until the replay is gone."""

    def __init__(
        self, store: ReplayStore, producers: ReplayProducers, policy: ReplayPolicy
    ) -> None:
        self._store = store
        self._producers = producers
        self._block_s = policy.tick_s

    async def __call__(
        self, replay_id: str, after: str | None
    ) -> AsyncIterator[StreamEntry | ReplayFailure]:
        if await self._store.state(replay_id) is None:
            raise ReplayNotFoundError(f"replay {replay_id} does not exist or has expired")
        # A producer that died with its process resumes as soon as someone watches.
        self._producers.ensure(replay_id)
        return self._entries(replay_id, after)

    async def _entries(
        self, replay_id: str, after: str | None
    ) -> AsyncIterator[StreamEntry | ReplayFailure]:
        while (read := await self._store.read(replay_id, after, self._block_s)) is not None:
            for entry in read.entries:
                yield entry
                after = entry.entry_id
            if read.state.failure is not None:
                yield ReplayFailure(read.state.failure)
                return
