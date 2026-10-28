import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from datetime import UTC, datetime, timedelta

import httpx2
from pymongo import AsyncMongoClient

from f1_strategy.adapters.clean_store import PostgresCleanStore, connection_pool
from f1_strategy.adapters.openf1 import OpenF1Client, OpenF1Error
from f1_strategy.adapters.rate_limit import RateLimit, SlidingWindowRateLimiter
from f1_strategy.adapters.raw_store import MongoDocument, MongoRawStore
from f1_strategy.adapters.settings import Settings
from f1_strategy.application.ingestion import (
    IngestionReport,
    IngestLatestGrandPrixTelemetry,
    IngestSeason,
    IngestSessionTelemetry,
    RawSource,
    RawStore,
    SessionNotFoundError,
    SessionNotSettledError,
)
from f1_strategy.application.transform import (
    Outcome,
    SeasonNotIngestedError,
    TransformPolicy,
    TransformReport,
    TransformSeason,
)
from f1_strategy.domain.clean import CleanDataError
from f1_strategy.domain.openf1 import OpenF1PayloadError, SessionType
from f1_strategy.domain.retry import RetryPolicy

SECOND_S = 1.0
MINUTE_S = 60.0
DEFAULT_SESSION_TYPES = (SessionType.RACE, SessionType.QUALIFYING)
EXPECTED_FAILURES = (
    OpenF1Error,
    OpenF1PayloadError,
    SessionNotFoundError,
    SessionNotSettledError,
    SeasonNotIngestedError,
    CleanDataError,
)

type Clock = Callable[[], datetime]
type Command = Callable[
    [argparse.Namespace, Settings, httpx2.AsyncBaseTransport | None, Clock],
    Coroutine[object, object, int],
]
type Ingest = Callable[
    [argparse.Namespace, RawSource, RawStore, Settings, datetime], Awaitable[IngestionReport]
]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def main(
    argv: Sequence[str] | None = None,
    transport: httpx2.AsyncBaseTransport | None = None,
    clock: Clock = _utc_now,
) -> int:
    args = _parser().parse_args(argv)
    command: Command = args.command
    try:
        # The async PostgreSQL driver cannot run on the proactor loop that Windows uses by
        # default; the selector loop is the default elsewhere, so every platform runs the same.
        return asyncio.run(
            command(args, Settings(), transport, clock), loop_factory=asyncio.SelectorEventLoop
        )
    except EXPECTED_FAILURES as error:
        print(f"{args.failure} failed: {error}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="f1-strategy", description="Ingest raw OpenF1 data and load it into the clean model"
    )
    commands = parser.add_subparsers(required=True)
    season = commands.add_parser("season", help="ingest every settled session of a season")
    _season_arguments(season)
    season.set_defaults(command=_ingest, ingest=_ingest_season, failure="ingestion")
    telemetry = commands.add_parser(
        "telemetry",
        help="car_data and location of one session; other sessions' telemetry is deleted",
    )
    telemetry.add_argument("--session-key", type=int, help="default: the latest settled Grand Prix")
    telemetry.set_defaults(command=_ingest, ingest=_ingest_telemetry, failure="ingestion")
    transform = commands.add_parser(
        "transform", help="load the ingested sessions of a season into the clean model"
    )
    _season_arguments(transform)
    transform.set_defaults(command=_transform, failure="transform")
    return parser


def _season_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--session-type",
        type=SessionType,
        action="append",
        choices=list(SessionType),
        dest="session_types",
        help=f"repeatable; default: {', '.join(DEFAULT_SESSION_TYPES)}",
    )


async def _ingest(
    args: argparse.Namespace,
    settings: Settings,
    transport: httpx2.AsyncBaseTransport | None,
    clock: Clock,
) -> int:
    async with (
        _mongo(settings) as mongo,
        httpx2.AsyncClient(
            base_url=str(settings.openf1_base_url),
            timeout=settings.openf1_timeout_s,
            transport=transport,
        ) as http,
    ):
        source = _source(http, settings, clock)
        store = MongoRawStore(mongo, settings.mongo_database)
        await store.ensure_indexes()
        ingest: Ingest = args.ingest
        report = await ingest(args, source, store, settings, clock())
    print(_summary(report))
    return 0


async def _transform(
    args: argparse.Namespace,
    settings: Settings,
    _transport: httpx2.AsyncBaseTransport | None,
    clock: Clock,
) -> int:
    pool = connection_pool(
        settings.postgres_uri.get_secret_value(),
        # One connection per worker, and one for the run table writes outside a claim.
        max_size=settings.transform_max_concurrency + 1,
        connect_timeout_s=settings.postgres_connect_timeout_s,
    )
    async with _mongo(settings) as mongo, pool:
        transform = TransformSeason(
            MongoRawStore(mongo, settings.mongo_database),
            PostgresCleanStore(pool),
            TransformPolicy(
                settings.transform_max_concurrency,
                RetryPolicy(settings.transform_max_attempts, settings.transform_backoff_base_s),
                timedelta(hours=settings.session_settle_h),
            ),
        )
        session_types = args.session_types or DEFAULT_SESSION_TYPES
        report = await transform(args.year, frozenset(session_types), clock())
    print(_transform_summary(report))
    for failure in report.failures:
        print(f"session {failure.session_key} failed: {failure.error}", file=sys.stderr)
    return 1 if report.failures else 0


def _mongo(settings: Settings) -> AsyncMongoClient[MongoDocument]:
    return AsyncMongoClient(settings.mongo_uri.get_secret_value(), tz_aware=True)


async def _ingest_season(
    args: argparse.Namespace,
    source: RawSource,
    store: RawStore,
    settings: Settings,
    now: datetime,
) -> IngestionReport:
    ingest_season = IngestSeason(
        source,
        store,
        settings.openf1_max_concurrency,
        timedelta(hours=settings.session_settle_h),
    )
    session_types = args.session_types or DEFAULT_SESSION_TYPES
    return await ingest_season(args.year, frozenset(session_types), now)


async def _ingest_telemetry(
    args: argparse.Namespace,
    source: RawSource,
    store: RawStore,
    settings: Settings,
    now: datetime,
) -> IngestionReport:
    adapters = (
        source,
        store,
        settings.openf1_max_concurrency,
        timedelta(hours=settings.session_settle_h),
        timedelta(minutes=settings.telemetry_window_min),
    )
    if args.session_key is None:
        return await IngestLatestGrandPrixTelemetry(*adapters)(now)
    return await IngestSessionTelemetry(*adapters)(args.session_key, now)


def _source(http: httpx2.AsyncClient, settings: Settings, clock: Clock) -> OpenF1Client:
    limiter = SlidingWindowRateLimiter(
        [
            RateLimit(settings.openf1_requests_per_second, SECOND_S),
            RateLimit(settings.openf1_requests_per_minute, MINUTE_S),
        ]
    )
    return OpenF1Client(
        http,
        limiter,
        RetryPolicy(settings.openf1_max_attempts, settings.openf1_backoff_base_s),
        clock=clock,
    )


def _transform_summary(report: TransformReport) -> str:
    counts = ", ".join(f"{report.count(outcome)} {outcome}" for outcome in Outcome)
    return f"transformed {len(report.outcomes)} sessions: {counts}"


def _summary(report: IngestionReport) -> str:
    return (
        f"ingested {report.sessions} sessions: {report.requests} requests, "
        f"{report.fetched} fetched, {report.already_stored} already stored, "
        f"{report.deleted} deleted"
    )


if __name__ == "__main__":
    sys.exit(main())
