import logging

from sqlalchemy.orm import Session

from src.config import settings
from src.core.entities.driver import DriverCreate, OpenF1DriverResponse
from src.core.entities.interval import IntervalCreate, OpenF1IntervalResponse
from src.core.entities.lap import LapCreate, OpenF1LapResponse
from src.core.entities.session import OpenF1SessionResponse, SessionCreate
from src.infrastructure.clients.openf1_client import OpenF1Client
from src.infrastructure.database.repositories.driver_repo import upsert_drivers
from src.infrastructure.database.repositories.interval_repo import (
    bulk_insert_intervals,
    session_intervals_exist,
)
from src.infrastructure.database.repositories.lap_repo import (
    bulk_insert_laps,
    session_laps_exist,
)
from src.infrastructure.database.repositories.session_repo import upsert_sessions
from src.infrastructure.storage.s3_client import S3Client

logger = logging.getLogger(__name__)


def _to_driver_create(raw: dict) -> DriverCreate | None:
    parsed = OpenF1DriverResponse.model_validate(raw)
    if not parsed.full_name:
        return None
    return DriverCreate(
        driver_number=parsed.driver_number,
        full_name=parsed.full_name,
        team_name=parsed.team_name or "Unknown",
        country_code=parsed.country_code,
    )


def _to_session_create(raw: dict) -> SessionCreate | None:
    parsed = OpenF1SessionResponse.model_validate(raw)
    if not parsed.year or not parsed.circuit_short_name:
        return None
    return SessionCreate(
        session_key=parsed.session_key,
        session_name=parsed.session_name,
        circuit_short_name=parsed.circuit_short_name,
        date_start=parsed.date_start,
        year=parsed.year,
    )


def _to_lap_create(raw: dict) -> LapCreate | None:
    parsed = OpenF1LapResponse.model_validate(raw)
    if parsed.session_key is None or parsed.driver_number is None or parsed.lap_number is None:
        return None
    duration_ms = int(parsed.lap_duration * 1000) if parsed.lap_duration is not None else None
    return LapCreate(
        session_key=parsed.session_key,
        driver_number=parsed.driver_number,
        lap_number=parsed.lap_number,
        duration_ms=duration_ms,
        is_pit_out_lap=parsed.is_pit_out_lap or False,
        stint=None,
    )


def _to_interval_create(raw: dict) -> IntervalCreate | None:
    parsed = OpenF1IntervalResponse.model_validate(raw)
    if parsed.session_key is None or parsed.driver_number is None:
        return None
    return IntervalCreate(
        session_key=parsed.session_key,
        driver_number=parsed.driver_number,
        gap_to_leader=str(parsed.gap_to_leader) if parsed.gap_to_leader is not None else None,
        interval=str(parsed.interval) if parsed.interval is not None else None,
        date=parsed.date,
    )


class SeasonIngestionUseCase:
    def __init__(self, openf1: OpenF1Client, s3: S3Client, db: Session) -> None:
        self._openf1 = openf1
        self._s3 = s3
        self._db = db
        self._bucket = settings.S3_BUCKET_NAME

    def run(self, year: int) -> None:
        logger.info("Starting ingestion for year %s", year)
        self._s3.ensure_bucket(self._bucket)

        raw_sessions = self._openf1.get_sessions(year)
        self._s3.save_raw(self._bucket, f"sessions/{year}/sessions.json", raw_sessions)

        sessions = [s for raw in raw_sessions if (s := _to_session_create(raw))]
        upsert_sessions(self._db, sessions)
        logger.info("  Sessions upserted: %d", len(sessions))

        for raw_session in raw_sessions:
            session_key = raw_session.get("session_key")
            session_type = raw_session.get("session_type", "")
            session_name = raw_session.get("session_name", "")
            if not session_key:
                continue

            logger.info("  Processing session %s (%s)", session_key, session_name)
            self._ingest_drivers(session_key, year)
            self._ingest_laps(session_key, year)

            if session_type == "Race":
                self._ingest_intervals(session_key, year)

        logger.info("Ingestion for year %s complete.", year)

    def _ingest_drivers(self, session_key: int, year: int) -> None:
        raw = self._openf1.get_drivers(session_key)
        self._s3.save_raw(self._bucket, f"drivers/{year}/session_{session_key}.json", raw)
        drivers = [d for r in raw if (d := _to_driver_create(r))]
        upsert_drivers(self._db, drivers)
        logger.info("    Drivers upserted: %d", len(drivers))

    def _ingest_laps(self, session_key: int, year: int) -> None:
        if session_laps_exist(self._db, session_key):
            logger.info("    Laps already exist for session %s, skipping.", session_key)
            return
        raw = self._openf1.get_laps(session_key)
        self._s3.save_raw(self._bucket, f"laps/{year}/session_{session_key}.json", raw)
        laps = [lap for r in raw if (lap := _to_lap_create(r))]
        bulk_insert_laps(self._db, laps)
        logger.info("    Laps inserted: %d", len(laps))

    def _ingest_intervals(self, session_key: int, year: int) -> None:
        if session_intervals_exist(self._db, session_key):
            logger.info("    Intervals already exist for session %s, skipping.", session_key)
            return
        raw = self._openf1.get_intervals(session_key)
        self._s3.save_raw(self._bucket, f"intervals/{year}/session_{session_key}.json", raw)
        intervals = [iv for r in raw if (iv := _to_interval_create(r))]
        bulk_insert_intervals(self._db, intervals)
        logger.info("    Intervals inserted: %d", len(intervals))
