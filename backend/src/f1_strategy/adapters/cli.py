import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta

import httpx2
from pymongo import AsyncMongoClient

from f1_strategy.adapters.openf1 import OpenF1Client, OpenF1Error, RetryPolicy
from f1_strategy.adapters.rate_limit import RateLimit, SlidingWindowRateLimiter
from f1_strategy.adapters.raw_store import MongoDocument, MongoRawStore
from f1_strategy.adapters.settings import Settings
from f1_strategy.application.ingestion import (
    IngestionReport,
    IngestSeason,
    IngestSessionTelemetry,
    RawSource,
    RawStore,
    SessionNotFoundError,
    SessionNotSettledError,
)
from f1_strategy.domain.openf1 import OpenF1PayloadError, SessionType

SECOND_S = 1.0
MINUTE_S = 60.0
DEFAULT_SESSION_TYPES = (SessionType.RACE, SessionType.QUALIFYING)
EXPECTED_FAILURES = (
    OpenF1Error,
    OpenF1PayloadError,
    SessionNotFoundError,
    SessionNotSettledError,
)

type Clock = Callable[[], datetime]
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
    try:
        report = asyncio.run(_run(args, Settings(), transport, clock))
    except EXPECTED_FAILURES as error:
        print(f"ingestion failed: {error}", file=sys.stderr)
        return 1
    print(_summary(report))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="f1-ingest", description="Ingest raw OpenF1 data")
    commands = parser.add_subparsers(required=True)
    season = commands.add_parser("season", help="every settled session of a season")
    season.add_argument("--year", type=int, required=True)
    season.add_argument(
        "--session-type",
        type=SessionType,
        action="append",
        choices=list(SessionType),
        dest="session_types",
        help=f"repeatable; default: {', '.join(DEFAULT_SESSION_TYPES)}",
    )
    season.set_defaults(ingest=_ingest_season)
    telemetry = commands.add_parser("telemetry", help="car_data and location of one session")
    telemetry.add_argument("--session-key", type=int, required=True)
    telemetry.set_defaults(ingest=_ingest_telemetry)
    return parser


async def _run(
    args: argparse.Namespace,
    settings: Settings,
    transport: httpx2.AsyncBaseTransport | None,
    clock: Clock,
) -> IngestionReport:
    mongo: AsyncMongoClient[MongoDocument] = AsyncMongoClient(
        settings.mongo_uri.get_secret_value(), tz_aware=True
    )
    async with (
        mongo,
        httpx2.AsyncClient(
            base_url=str(settings.openf1_base_url),
            timeout=settings.openf1_timeout_s,
            transport=transport,
        ) as http,
    ):
        source = _source(http, settings, clock)
        store = MongoRawStore(mongo, settings.mongo_database)
        ingest: Ingest = args.ingest
        return await ingest(args, source, store, settings, clock())


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
    ingest_telemetry = IngestSessionTelemetry(
        source,
        store,
        settings.openf1_max_concurrency,
        timedelta(hours=settings.session_settle_h),
        timedelta(minutes=settings.telemetry_window_min),
    )
    return await ingest_telemetry(args.session_key, now)


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


def _summary(report: IngestionReport) -> str:
    return (
        f"ingested {report.sessions} sessions: {report.requests} requests, "
        f"{report.fetched} fetched, {report.already_stored} already stored"
    )


if __name__ == "__main__":
    sys.exit(main())
