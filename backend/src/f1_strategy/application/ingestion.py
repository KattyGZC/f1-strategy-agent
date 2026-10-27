import asyncio
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from f1_strategy.domain.openf1 import (
    JsonObject,
    RawRequest,
    RawResponse,
    Session,
    SessionType,
    drivers_request,
    meetings_request,
    parse_driver_numbers,
    parse_sessions,
    season_sessions_request,
    session_request,
    session_requests,
    telemetry_requests,
)


class RawSource(Protocol):
    async def fetch(self, request: RawRequest) -> RawResponse: ...


class RawStore(Protocol):
    async def contains(self, request: RawRequest) -> bool: ...

    async def rows(self, request: RawRequest) -> list[JsonObject] | None: ...

    async def put(self, response: RawResponse) -> None: ...


@dataclass(frozen=True)
class IngestionReport:
    sessions: int
    requests: int
    fetched: int

    @property
    def already_stored(self) -> int:
        return self.requests - self.fetched


class SeasonNotFinishedError(ValueError):
    pass


class SessionNotFoundError(LookupError):
    pass


class SessionNotEndedError(ValueError):
    pass


class _Ingestor:
    def __init__(self, source: RawSource, store: RawStore, max_concurrency: int) -> None:
        if max_concurrency < 1:
            raise ValueError(f"max_concurrency must be at least 1, got {max_concurrency}")
        self._source = source
        self._store = store
        self._max_concurrency = max_concurrency
        self._requests = 0
        self._fetched = 0

    async def rows(self, request: RawRequest) -> list[JsonObject]:
        self._requests += 1
        stored = await self._store.rows(request)
        if stored is not None:
            return stored
        response = await self._fetch_and_store(request)
        return response.rows

    async def ensure_all(self, requests: Sequence[RawRequest]) -> None:
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def ensure(request: RawRequest) -> None:
            async with semaphore:
                self._requests += 1
                if not await self._store.contains(request):
                    await self._fetch_and_store(request)

        try:
            async with asyncio.TaskGroup() as group:
                for request in requests:
                    group.create_task(ensure(request))
        except ExceptionGroup as failures:
            raise failures.exceptions[0] from failures

    def report(self, sessions: int) -> IngestionReport:
        return IngestionReport(sessions=sessions, requests=self._requests, fetched=self._fetched)

    async def _fetch_and_store(self, request: RawRequest) -> RawResponse:
        response = await self._source.fetch(request)
        await self._store.put(response)
        self._fetched += 1
        return response


class IngestSeason:
    def __init__(self, source: RawSource, store: RawStore, max_concurrency: int) -> None:
        self._source = source
        self._store = store
        self._max_concurrency = max_concurrency

    async def __call__(
        self, year: int, session_types: Collection[SessionType], now: datetime
    ) -> IngestionReport:
        if year >= now.year:
            raise SeasonNotFinishedError(
                f"season {year} is not finished; only seasons before {now.year} are ingested"
            )
        ingestor = _Ingestor(self._source, self._store, self._max_concurrency)
        await ingestor.ensure_all([meetings_request(year)])
        sessions = [
            session
            for session in parse_sessions(await ingestor.rows(season_sessions_request(year)))
            if session.session_type in session_types and not session.is_cancelled
        ]
        await ingestor.ensure_all(
            [request for session in sessions for request in session_requests(session)]
        )
        return ingestor.report(sessions=len(sessions))


class IngestSessionTelemetry:
    def __init__(
        self, source: RawSource, store: RawStore, max_concurrency: int, window: timedelta
    ) -> None:
        self._source = source
        self._store = store
        self._max_concurrency = max_concurrency
        self._window = window

    async def __call__(self, session_key: int, now: datetime) -> IngestionReport:
        ingestor = _Ingestor(self._source, self._store, self._max_concurrency)
        session = _single_session(session_key, await ingestor.rows(session_request(session_key)))
        if session.date_end > now:
            raise SessionNotEndedError(
                f"session {session_key} ends at {session.date_end.isoformat()}"
            )
        driver_numbers = parse_driver_numbers(await ingestor.rows(drivers_request(session_key)))
        await ingestor.ensure_all(telemetry_requests(session, driver_numbers, self._window))
        return ingestor.report(sessions=1)


def _single_session(session_key: int, rows: list[JsonObject]) -> Session:
    sessions = parse_sessions(rows)
    if len(sessions) != 1:
        raise SessionNotFoundError(
            f"expected one session with session_key={session_key}, OpenF1 returned {len(sessions)}"
        )
    return sessions[0]
