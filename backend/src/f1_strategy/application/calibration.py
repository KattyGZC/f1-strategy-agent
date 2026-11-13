"""The sweep that keeps each race's lap-time model in step with its clean rows (ADR 0014)."""

import asyncio
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from f1_strategy.domain.clean_laps import CalibrationDataError, RaceRows
from f1_strategy.domain.lap_time_model import (
    CALIBRATION_VERSION,
    Calibration,
    NotCalibrated,
    calibrate,
)

UNCHANGED_FAILURE = "unchanged since it failed"


class SeasonNotTransformedError(LookupError):
    def __init__(self, year: int) -> None:
        super().__init__(f"no race of {year} is in the clean model; run the transform first")


class CalibrationStatus(StrEnum):
    CALIBRATED = "calibrated"
    NOT_CALIBRATED = "not_calibrated"
    FAILED = "failed"


class CalibrationOutcome(StrEnum):
    CALIBRATED = "calibrated"
    NOT_CALIBRATED = "not_calibrated"
    UNCHANGED = "unchanged"
    STILL_FAILING = "still_failing"
    FAILED = "failed"
    GONE = "gone"


@dataclass(frozen=True)
class Fingerprint:
    """What a calibration is a function of: the race's clean rows and the model."""

    clean_output_hash: str
    calibration_version: str


@dataclass(frozen=True)
class StoredCalibration:
    status: CalibrationStatus
    fingerprint: Fingerprint


@dataclass(frozen=True)
class Race:
    session_key: int
    clean_output_hash: str


@dataclass(frozen=True)
class RaceSnapshot:
    rows: RaceRows
    clean_output_hash: str


@dataclass(frozen=True)
class CalibrationFailed:
    message: str


type CalibrationResult = Calibration | NotCalibrated | CalibrationFailed


class CalibrationStore(Protocol):
    async def races(self, year: int) -> tuple[Race, ...]:
        """The season's loaded Grand Prix races, by session key."""
        ...

    async def stored(self, session_keys: Collection[int]) -> dict[int, StoredCalibration]: ...

    async def snapshot(self, session_key: int) -> RaceSnapshot | None:
        """The race's rows and the hash of its clean rows, from one snapshot; None when the
        session is no longer loaded."""
        ...

    async def save(
        self, session_key: int, fingerprint: Fingerprint, result: CalibrationResult, now: datetime
    ) -> None:
        """Replace the race's calibration with the result; every row commits together."""
        ...


@dataclass(frozen=True)
class RaceOutcome:
    session_key: int
    outcome: CalibrationOutcome
    error: str | None = None


@dataclass(frozen=True)
class CalibrationReport:
    outcomes: tuple[RaceOutcome, ...]

    def count(self, outcome: CalibrationOutcome) -> int:
        return sum(1 for race in self.outcomes if race.outcome == outcome)

    @property
    def failures(self) -> tuple[RaceOutcome, ...]:
        failing = (CalibrationOutcome.FAILED, CalibrationOutcome.STILL_FAILING)
        return tuple(race for race in self.outcomes if race.outcome in failing)


class CalibrateSeason:
    def __init__(self, store: CalibrationStore) -> None:
        self._store = store

    async def __call__(self, year: int, now: datetime) -> CalibrationReport:
        races = await self._store.races(year)
        if not races:
            raise SeasonNotTransformedError(year)
        stored = await self._store.stored([race.session_key for race in races])
        outcomes = [await self._race(race, stored.get(race.session_key), now) for race in races]
        return CalibrationReport(tuple(outcomes))

    async def _race(
        self, race: Race, stored: StoredCalibration | None, now: datetime
    ) -> RaceOutcome:
        key = race.session_key
        if stored is not None and stored.fingerprint == _fingerprint(race.clean_output_hash):
            if stored.status == CalibrationStatus.FAILED:
                return RaceOutcome(key, CalibrationOutcome.STILL_FAILING, UNCHANGED_FAILURE)
            return RaceOutcome(key, CalibrationOutcome.UNCHANGED)
        snapshot = await self._store.snapshot(key)
        if snapshot is None:
            return RaceOutcome(key, CalibrationOutcome.GONE)
        # CPU-bound for about a tenth of a second on a race; a thread keeps the event loop free.
        result = await asyncio.to_thread(_calibrated, snapshot.rows)
        await self._store.save(key, _fingerprint(snapshot.clean_output_hash), result, now)
        if isinstance(result, Calibration):
            return RaceOutcome(key, CalibrationOutcome.CALIBRATED)
        if isinstance(result, NotCalibrated):
            return RaceOutcome(key, CalibrationOutcome.NOT_CALIBRATED, result.reason)
        return RaceOutcome(key, CalibrationOutcome.FAILED, result.message)


def _calibrated(rows: RaceRows) -> CalibrationResult:
    try:
        return calibrate(rows)
    except CalibrationDataError as error:
        return CalibrationFailed(str(error))


def _fingerprint(clean_output_hash: str) -> Fingerprint:
    return Fingerprint(clean_output_hash, CALIBRATION_VERSION)
