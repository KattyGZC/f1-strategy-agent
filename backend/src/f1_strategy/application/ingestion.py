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
    chosen_sessions,
    drivers_request,
    grand_prix_request,
    latest_race,
    meetings_request,
    parse_driver_numbers,
    parse_sessions,
    season_cutoff,
    season_sessions_request,
    session_request,
    session_requests,
    settled_cutoff,
    telemetry_requests,
)


class RawSource(Protocol):
    async def fetch(self, request: RawRequest) -> RawResponse: ...


class RawStore(Protocol):
    async def contains(self, request: RawRequest) -> bool: ...

    async def rows(self, request: RawRequest) -> list[JsonObject] | None: ...

    async def put(self, response: RawResponse) -> None: ...

    async def delete_telemetry_except(self, session_key: int) -> int: ...


@dataclass(frozen=True)
class IngestionReport:
    sessions: int
    requests: int
    fetched: int
    deleted: int

    @property
    def already_stored(self) -> int:
        return self.requests - self.fetched


class SessionNotFoundError(LookupError):
    pass


class SessionNotSettledError(ValueError):
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
        self._deleted = 0

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

    async def delete_telemetry_except(self, session_key: int) -> None:
        self._deleted += await self._store.delete_telemetry_except(session_key)

    def report(self, sessions: int) -> IngestionReport:
        return IngestionReport(
            sessions=sessions,
            requests=self._requests,
            fetched=self._fetched,
            deleted=self._deleted,
        )

    async def _fetch_and_store(self, request: RawRequest) -> RawResponse:
        response = await self._source.fetch(request)
        await self._store.put(response)
        self._fetched += 1
        return response


class IngestSeason:
    def __init__(
        self, source: RawSource, store: RawStore, max_concurrency: int, settle_time: timedelta
    ) -> None:
        self._source = source
        self._store = store
        self._max_concurrency = max_concurrency
        self._settle_time = settle_time

    async def __call__(
        self, year: int, session_types: Collection[SessionType], now: datetime
    ) -> IngestionReport:
        ingestor = _Ingestor(self._source, self._store, self._max_concurrency)
        cutoff = season_cutoff(year, now, self._settle_time)
        await ingestor.ensure_all([meetings_request(year, cutoff)])
        index = await ingestor.rows(season_sessions_request(year, cutoff))
        sessions = chosen_sessions(index, session_types, cutoff)
        await ingestor.ensure_all(
            [request for session in sessions for request in session_requests(session)]
        )
        return ingestor.report(sessions=len(sessions))


class _TelemetryIngestion:
    def __init__(
        self,
        source: RawSource,
        store: RawStore,
        max_concurrency: int,
        settle_time: timedelta,
        window: timedelta,
    ) -> None:
        self._source = source
        self._store = store
        self._max_concurrency = max_concurrency
        self._settle_time = settle_time
        self._window = window

    def _ingestor(self) -> _Ingestor:
        return _Ingestor(self._source, self._store, self._max_concurrency)

    async def _ingest(self, ingestor: _Ingestor, session: Session) -> IngestionReport:
        driver_numbers = parse_driver_numbers(
            await ingestor.rows(drivers_request(session.session_key))
        )
        await ingestor.ensure_all(telemetry_requests(session, driver_numbers, self._window))
        await ingestor.delete_telemetry_except(session.session_key)
        return ingestor.report(sessions=1)


class IngestSessionTelemetry(_TelemetryIngestion):
    async def __call__(self, session_key: int, now: datetime) -> IngestionReport:
        ingestor = self._ingestor()
        session = _single_session(session_key, await ingestor.rows(session_request(session_key)))
        settles_at = session.settles_at(self._settle_time)
        if settles_at > now:
            raise SessionNotSettledError(
                f"session {session_key} ends at {session.date_end.isoformat()}; "
                f"it can be ingested from {settles_at.isoformat()}"
            )
        return await self._ingest(ingestor, session)


class IngestLatestGrandPrixTelemetry(_TelemetryIngestion):
    async def __call__(self, now: datetime) -> IngestionReport:
        ingestor = self._ingestor()
        cutoff = settled_cutoff(now, self._settle_time)
        races = parse_sessions(await ingestor.rows(grand_prix_request(cutoff)))
        session = latest_race(races, cutoff)
        if session is None:
            raise SessionNotFoundError(f"no Grand Prix settled before {cutoff.isoformat()}")
        return await self._ingest(ingestor, session)


def _single_session(session_key: int, rows: list[JsonObject]) -> Session:
    sessions = parse_sessions(rows)
    if len(sessions) != 1:
        raise SessionNotFoundError(
            f"expected one session with session_key={session_key}, OpenF1 returned {len(sessions)}"
        )
    return sessions[0]
