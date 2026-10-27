"""The reconciling sweep that keeps the clean model in step with the raw store (ADR 0008)."""

import asyncio
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from f1_strategy.domain.clean import (
    TRANSFORM_VERSION,
    CleanDataError,
    CleanSession,
    RawSession,
    clean_session,
    content_hash,
    input_fingerprint,
)
from f1_strategy.domain.openf1 import (
    Endpoint,
    JsonObject,
    RawRequest,
    Session,
    SessionType,
    chosen_sessions,
    meetings_request,
    season_cutoff,
    season_sessions_request,
    session_requests,
)
from f1_strategy.domain.retry import RetryPolicy

type Sleep = Callable[[float], Awaitable[None]]


class TransientError(Exception):
    """A failure that can succeed on retry. Adapters raise it for lost connections,
    serialization failures and deadlocks; anything else fails the session for good."""


class SeasonNotIngestedError(LookupError):
    pass


class RunStatus(StrEnum):
    PENDING = "pending"
    WAITING_RAW = "waiting_raw"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ErrorKind(StrEnum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"


class Outcome(StrEnum):
    LOADED = "loaded"
    UNCHANGED = "unchanged"
    WAITING_RAW = "waiting_raw"
    STILL_FAILING = "still_failing"
    FAILED = "failed"
    BUSY = "busy"


@dataclass(frozen=True)
class Version:
    """What a load is a function of: its input and the transform that read it."""

    input_fingerprint: str
    transform_version: str


@dataclass(frozen=True)
class RunState:
    status: RunStatus
    current: Version
    error_kind: ErrorKind | None
    loaded: Version | None


@dataclass(frozen=True)
class Load:
    clean: CleanSession
    version: Version
    output_hash: str
    loaded_at: datetime


class Claim(Protocol):
    """A session held by one worker until the claim's transaction ends."""

    @property
    def state(self) -> RunState: ...

    async def replace(self, load: Load) -> None:
        """Replace the session's clean rows and record the load; both commit together."""
        ...


class CleanStore(Protocol):
    async def runs(self, session_keys: Collection[int]) -> dict[int, RunState]: ...

    def claim(
        self, session_key: int, version: Version, now: datetime
    ) -> AbstractAsyncContextManager[Claim | None]:
        """Hold the session for the block, or yield None when another worker holds it."""
        ...

    async def record_waiting(self, session_key: int, version: Version, now: datetime) -> None: ...

    async def record_failure(
        self, session_key: int, version: Version, kind: ErrorKind, message: str, now: datetime
    ) -> None: ...


class RawDocuments(Protocol):
    async def rows(self, request: RawRequest) -> list[JsonObject] | None: ...

    async def fetched_at(self, requests: Sequence[RawRequest]) -> dict[str, datetime]:
        """The fetch time of each stored request, by key; a request not stored is absent."""
        ...


@dataclass(frozen=True)
class SessionOutcome:
    session_key: int
    outcome: Outcome
    error: str | None = None


@dataclass(frozen=True)
class TransformReport:
    outcomes: tuple[SessionOutcome, ...]

    def count(self, outcome: Outcome) -> int:
        return sum(1 for session in self.outcomes if session.outcome == outcome)

    @property
    def failures(self) -> tuple[SessionOutcome, ...]:
        failing = (Outcome.FAILED, Outcome.STILL_FAILING)
        return tuple(session for session in self.outcomes if session.outcome in failing)


@dataclass(frozen=True)
class _SeasonInput:
    index_request: RawRequest
    meetings_request: RawRequest
    session_rows: Mapping[int, JsonObject]
    meeting_rows: Mapping[int, JsonObject]


@dataclass(frozen=True)
class TransformPolicy:
    max_concurrency: int
    retry: RetryPolicy
    settle_time: timedelta

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError(f"max_concurrency must be at least 1, got {self.max_concurrency}")


class TransformSeason:
    def __init__(
        self,
        raw: RawDocuments,
        clean: CleanStore,
        policy: TransformPolicy,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._raw = raw
        self._clean = clean
        self._max_concurrency = policy.max_concurrency
        self._retry = policy.retry
        self._settle_time = policy.settle_time
        self._sleep = sleep

    async def __call__(
        self, year: int, session_types: Collection[SessionType], now: datetime
    ) -> TransformReport:
        cutoff = season_cutoff(year, now, self._settle_time)
        season = await self._season_input(year, cutoff)
        sessions = chosen_sessions(list(season.session_rows.values()), session_types, cutoff)
        states = await self._clean.runs([session.session_key for session in sessions])
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def bounded(session: Session) -> SessionOutcome:
            async with semaphore:
                return await self._session(season, session, states.get(session.session_key), now)

        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(bounded(session)) for session in sessions]
        outcomes = sorted((task.result() for task in tasks), key=lambda done: done.session_key)
        return TransformReport(tuple(outcomes))

    async def _season_input(self, year: int, cutoff: datetime) -> _SeasonInput:
        index_request = season_sessions_request(year, cutoff)
        calendar_request = meetings_request(year, cutoff)
        index = await self._raw.rows(index_request)
        calendar = await self._raw.rows(calendar_request)
        if index is None or calendar is None:
            missing = calendar_request if index is not None else index_request
            raise SeasonNotIngestedError(
                f"{missing.key} is not stored; ingest the season with the same clock first"
            )
        return _SeasonInput(
            index_request=index_request,
            meetings_request=calendar_request,
            session_rows=_by_key(index, Endpoint.SESSIONS, "session_key"),
            meeting_rows=_by_key(calendar, Endpoint.MEETINGS, "meeting_key"),
        )

    async def _session(
        self, season: _SeasonInput, session: Session, state: RunState | None, now: datetime
    ) -> SessionOutcome:
        key = session.session_key
        session_row = season.session_rows[key]
        meeting_key = session_row.get("meeting_key")
        meeting_row = season.meeting_rows.get(meeting_key) if isinstance(meeting_key, int) else None
        requests = session_requests(session)
        stamps = await self._raw.fetched_at(requests)
        version = Version(
            input_fingerprint(session_row, meeting_row or {}, stamps.items()), TRANSFORM_VERSION
        )
        if meeting_row is None:
            message = f"{season.meetings_request.key}: meeting {meeting_key!r} is not in it"
            return await self._failed(key, version, ErrorKind.PERMANENT, message, now)
        if len(stamps) < len(requests):
            await self._clean.record_waiting(key, version, now)
            return SessionOutcome(key, Outcome.WAITING_RAW)
        if state is not None and state.loaded == version:
            return SessionOutcome(key, Outcome.UNCHANGED)
        if (
            state is not None
            and state.status == RunStatus.FAILED
            and state.error_kind == ErrorKind.PERMANENT
            and state.current == version
        ):
            return SessionOutcome(key, Outcome.STILL_FAILING, "unchanged since it failed")
        raw = _RawSessionReader(self._raw, session_row, meeting_row, requests)
        return await self._load_with_retries(season, key, raw, version, now)

    async def _load_with_retries(
        self,
        season: _SeasonInput,
        key: int,
        raw: "_RawSessionReader",
        version: Version,
        now: datetime,
    ) -> SessionOutcome:
        attempt = 1
        while True:
            try:
                return await self._load(key, raw, version, now)
            except TransientError as error:
                if attempt == self._retry.max_attempts:
                    return await self._failed(key, version, ErrorKind.TRANSIENT, str(error), now)
                await self._sleep(self._retry.backoff_s(attempt))
                attempt += 1
            except CleanDataError as error:
                message = f"{_document_key(season, raw.requests, error.endpoint)}: {error}"
                return await self._failed(key, version, ErrorKind.PERMANENT, message, now)
            # A failure that is neither bad data nor transient (a constraint the database
            # enforces, a bug) fails this session for good and lets the others run.
            except Exception as error:
                message = f"{type(error).__name__}: {error}"
                return await self._failed(key, version, ErrorKind.PERMANENT, message, now)

    async def _load(
        self, key: int, raw: "_RawSessionReader", version: Version, now: datetime
    ) -> SessionOutcome:
        async with self._clean.claim(key, version, now) as claim:
            if claim is None:
                return SessionOutcome(key, Outcome.BUSY)
            if claim.state.loaded == version:
                return SessionOutcome(key, Outcome.UNCHANGED)
            raw_session = await raw.read()
            # CPU-bound for about half a second on a race; a thread keeps the event loop free.
            clean = await asyncio.to_thread(clean_session, raw_session)
            await claim.replace(Load(clean, version, content_hash(clean), now))
        return SessionOutcome(key, Outcome.LOADED)

    async def _failed(
        self, key: int, version: Version, kind: ErrorKind, message: str, now: datetime
    ) -> SessionOutcome:
        await self._clean.record_failure(key, version, kind, message, now)
        return SessionOutcome(key, Outcome.FAILED, message)


@dataclass(frozen=True)
class _RawSessionReader:
    raw: RawDocuments
    session_row: JsonObject
    meeting_row: JsonObject
    requests: tuple[RawRequest, ...]

    async def read(self) -> RawSession:
        rows: dict[Endpoint, list[JsonObject]] = {}
        for request in self.requests:
            stored = await self.raw.rows(request)
            if stored is None:
                raise TransientError(f"{request.key} disappeared while the session was read")
            rows[request.endpoint] = stored
        return RawSession(self.session_row, self.meeting_row, rows)


def _by_key(rows: Sequence[JsonObject], endpoint: Endpoint, field: str) -> dict[int, JsonObject]:
    by_key: dict[int, JsonObject] = {}
    for index, row in enumerate(rows):
        key = row.get(field)
        if not isinstance(key, int) or isinstance(key, bool):
            raise CleanDataError(endpoint, index, f"{field} must be an integer, got {key!r}")
        if key in by_key and by_key[key] != row:
            raise CleanDataError(endpoint, index, f"two different rows for {field} {key}")
        by_key[key] = row
    return by_key


def _document_key(season: _SeasonInput, requests: Sequence[RawRequest], endpoint: Endpoint) -> str:
    if endpoint == Endpoint.SESSIONS:
        return season.index_request.key
    if endpoint == Endpoint.MEETINGS:
        return season.meetings_request.key
    return next((request.key for request in requests if request.endpoint == endpoint), endpoint)
