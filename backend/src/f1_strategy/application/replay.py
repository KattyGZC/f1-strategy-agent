"""Replays: start, control and produce a paced copy of a session's timeline (ADR 0009).

The content of a replay is its session's timeline; pacing only decides when each event is
appended. What was appended is the progress: a producer that starts again resumes after it.
A seek starts a new generation of the stream, which the producer fills from the start
(ADR 0012).
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
    lap_start_s,
    offsets_s,
    paused,
    resumed,
    session_s_at,
    sought,
    started,
    wall_s_due,
    with_speed,
)
from f1_strategy.domain.replay import Event, EventKind, Timeline, TimelineRows, timeline


class SessionNotLoadedError(LookupError):
    def __init__(self, session_key: int) -> None:
        super().__init__(f"session {session_key} is not in the clean model")


class ReplayNotFoundError(LookupError):
    def __init__(self, replay_id: str) -> None:
        super().__init__(f"replay {replay_id} does not exist or has expired")


class ReplayFailedError(RuntimeError):
    def __init__(self, replay_id: str, failure: str) -> None:
        super().__init__(f"replay {replay_id} failed and cannot move: {failure}")


class LapNotFoundError(LookupError):
    def __init__(self, session_key: int, lap_number: int) -> None:
        super().__init__(f"session {session_key} has no start for lap {lap_number}")


class TooManyReplaysError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReplayState:
    """`generation` counts the seeks; the stream holds the latest generation only."""

    session_key: int
    playback: Playback
    failure: str | None = None
    generation: int = 0


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
class ReplayReset:
    """The first entry of a generation: a viewer drops what it built and rebuilds from the
    entries after it, the session from its start up to `session_s`."""

    entry_id: str
    lap_number: int
    session_s: float


@dataclass(frozen=True)
class StreamRead:
    state: ReplayState
    entries: tuple[StreamEntry | ReplayReset, ...]


@dataclass(frozen=True)
class ReplayFailure:
    message: str


class AppendOutcome(StrEnum):
    APPENDED = "appended"
    GONE = "gone"
    SUPERSEDED = "superseded"


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

    async def seek(
        self, replay_id: str, change: Callable[[ReplayState], ReplayState], lap_number: int
    ) -> ReplayState | None:
        """Apply `change`, which starts a new generation, and replace the stream with that
        generation's reset to `lap_number`, in one atomic step; None when the replay does not
        exist."""
        ...

    async def sent(self, replay_id: str) -> int:
        """How many events of the timeline the stream's latest generation holds."""
        ...

    async def append(
        self, replay_id: str, generation: int, first_index: int, events: Sequence[Event]
    ) -> AppendOutcome:
        """Appends nothing when the replay is gone or a seek superseded `generation`."""
        ...

    async def delete(self, replay_id: str) -> bool:
        """Remove the replay, its stream and its lease, freeing its place among the active
        replays; False when it did not exist."""
        ...

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
    """`append_batch` caps the events of one append: Redis runs an append alone, so a seek's
    catch-up goes in pieces between which every other replay's commands run."""

    tick_s: float
    lease_s: float
    append_batch: int

    def __post_init__(self) -> None:
        if not 0 < self.tick_s < self.lease_s:
            raise ValueError(
                f"tick_s must be positive and shorter than lease_s, got {self.tick_s}"
                f" and {self.lease_s}"
            )
        if self.append_batch < 1:
            raise ValueError(f"append_batch must be at least 1, got {self.append_batch}")


class ReplayEnd(StrEnum):
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
            raise ReplayNotFoundError(replay_id)
        return _status(state, self._clock())

    async def pause(self, replay_id: str) -> ReplayStatus:
        now = self._clock()
        return await self._change(replay_id, now, lambda playback: paused(playback, now))

    async def resume(self, replay_id: str) -> ReplayStatus:
        now = self._clock()
        return await self._change(replay_id, now, lambda playback: resumed(playback, now))

    async def set_speed(self, replay_id: str, speed: ReplaySpeed) -> ReplayStatus:
        now = self._clock()
        return await self._change(replay_id, now, lambda playback: with_speed(playback, speed, now))

    async def stop(self, replay_id: str) -> None:
        """Its producer and its viewers end as they would at its expiry."""
        if not await self._store.delete(replay_id):
            raise ReplayNotFoundError(replay_id)

    async def _change(
        self, replay_id: str, now: float, change: Callable[[Playback], Playback]
    ) -> ReplayStatus:
        state = await self._store.update(
            replay_id, lambda state: replace(state, playback=change(state.playback))
        )
        if state is None:
            raise ReplayNotFoundError(replay_id)
        return _status(state, now)


def _status(state: ReplayState, now: float) -> ReplayStatus:
    return ReplayStatus(state, session_s_at(state.playback, now))


async def session_timeline(rows: ReplayRows, session_key: int) -> Timeline:
    loaded = await rows.timeline_rows(session_key)
    if loaded is None:
        raise SessionNotLoadedError(session_key)
    # About 50 ms of CPU for a race's 30,000 events (measured 2026-11-04); a thread keeps
    # every other replay's stream moving meanwhile.
    return await asyncio.to_thread(timeline, loaded)


@dataclass(frozen=True)
class _Progress:
    generation: int
    sent: int


class ProduceReplay:
    """Appends a replay's events as they fall due, until the replay is gone. Past the end of
    the timeline it keeps ticking, so a seek back always finds a producer. One producer per
    replay at a time, held by a lease that each tick renews."""

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
        built = await session_timeline(self._rows, state.session_key)
        offsets = offsets_s(built)
        progress: _Progress | ReplayEnd = _Progress(
            state.generation, await self._store.sent(replay_id)
        )
        while isinstance(progress, _Progress):
            progress = await self._tick(replay_id, built.events, offsets, progress)
        return progress

    async def _tick(
        self, replay_id: str, events: Sequence[Event], offsets: Sequence[float], at: _Progress
    ) -> _Progress | ReplayEnd:
        """Appends what is due and waits for the next event; the progress now, or why the
        replay ended."""
        if not await self._hold(replay_id):
            return ReplayEnd.LEASE_LOST
        state = await self._store.state(replay_id)
        if state is None:
            return ReplayEnd.EXPIRED
        if state.generation != at.generation:
            at = _Progress(state.generation, await self._store.sent(replay_id))
        now = self._clock()
        sent = at.sent
        due = due_until(state.playback, offsets, sent, now)
        batch_end = min(due, sent + self._policy.append_batch)
        if batch_end > sent:
            outcome = await self._store.append(
                replay_id, at.generation, sent, events[sent:batch_end]
            )
            if outcome is AppendOutcome.GONE:
                return ReplayEnd.EXPIRED
            if outcome is AppendOutcome.APPENDED:
                sent = batch_end
        wait_s = 0.0 if due > sent else self._wait_s(state.playback, offsets[sent:], now)
        await self._clock.sleep(wait_s)
        return _Progress(at.generation, sent)

    def _wait_s(self, playback: Playback, unsent_offsets: Sequence[float], now: float) -> float:
        if isinstance(playback, Paused) or not unsent_offsets:
            return self._policy.tick_s
        next_due_s = wall_s_due(playback, unsent_offsets[0])
        return min(self._policy.tick_s, max(0.0, next_due_s - now))

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
            raise SessionNotLoadedError(session_key)
        replay_id = self._new_id()
        state = ReplayState(session_key, started(speed, self._clock()))
        if not await self._store.create(replay_id, state):
            raise TooManyReplaysError("the number of active replays is at its limit")
        self._producers.ensure(replay_id)
        return replay_id


class SeekReplay:
    """Moves a replay to the earliest start of a lap; its viewers rebuild from a reset."""

    def __init__(
        self, rows: ReplayRows, store: ReplayStore, producers: ReplayProducers, clock: WallClock
    ) -> None:
        self._rows = rows
        self._store = store
        self._producers = producers
        self._clock = clock

    async def __call__(self, replay_id: str, lap_number: int) -> ReplayStatus:
        state = await self._store.state(replay_id)
        if state is None:
            raise ReplayNotFoundError(replay_id)
        session_s = lap_start_s(await session_timeline(self._rows, state.session_key), lap_number)
        if session_s is None:
            raise LapNotFoundError(state.session_key, lap_number)
        now = self._clock()
        changed = await self._store.seek(
            replay_id, lambda state: _sought(replay_id, state, session_s, now), lap_number
        )
        if changed is None:
            raise ReplayNotFoundError(replay_id)
        # A producer that died with its process resumes here, as it does for a watch.
        self._producers.ensure(replay_id)
        return _status(changed, now)


def _sought(replay_id: str, state: ReplayState, session_s: float, now: float) -> ReplayState:
    # Checked on the state the seek's own transaction read, so a failure recorded meanwhile
    # is not sought.
    if state.failure is not None:
        raise ReplayFailedError(replay_id, state.failure)
    return replace(
        state, generation=state.generation + 1, playback=sought(state.playback, session_s, now)
    )


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
    ) -> AsyncIterator[StreamEntry | ReplayReset | ReplayFailure]:
        if await self._store.state(replay_id) is None:
            raise ReplayNotFoundError(replay_id)
        # A producer that died with its process resumes as soon as someone watches.
        self._producers.ensure(replay_id)
        return self._entries(replay_id, after)

    async def _entries(
        self, replay_id: str, after: str | None
    ) -> AsyncIterator[StreamEntry | ReplayReset | ReplayFailure]:
        while (read := await self._store.read(replay_id, after, self._block_s)) is not None:
            for entry in read.entries:
                yield entry
                after = entry.entry_id
            if read.state.failure is not None:
                yield ReplayFailure(read.state.failure)
                return
