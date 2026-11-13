"""Which laps of a race show the tyre and the car, and why each other lap does not (ADR 0014).

Every function here is pure. Each lap gets one verdict: clean, or excluded for the first
reason that applies, in the order `ExclusionReason` lists them.
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from statistics import median
from typing import Protocol

from f1_strategy.domain.clean import (
    Compound,
    Flag,
    FlagScope,
    Lap,
    Pit,
    RaceControl,
    RaceControlCategory,
    Stint,
    Weather,
)
from f1_strategy.domain.tyres import Tyre, TyreLookup

DRY_COMPOUNDS = (Compound.SOFT, Compound.MEDIUM, Compound.HARD)
CALIBRATED_COMPOUNDS = (*DRY_COMPOUNDS, Compound.INTERMEDIATE)

# The SafetyCar messages of the 2024 races (psql, 2026-11-12). A message outside both sets
# fails the race, so new wording is never read as racing.
NEUTRALISATION_STARTS = frozenset({"SAFETY CAR DEPLOYED", "VIRTUAL SAFETY CAR DEPLOYED"})
NEUTRALISATION_NOTICES = frozenset(
    {"SAFETY CAR IN THIS LAP", "VIRTUAL SAFETY CAR ENDING", "SAFETY CAR THROUGH THE PIT LANE"}
)
NEUTRALISATION_ENDS = frozenset({Flag.CLEAR, Flag.GREEN})

# Montreal 2024: slick laps were 1.092 times the dry pace 10 to 15 minutes after the last wet
# reading and back to it after 20 (ADR 0014).
DRYING_MARGIN = timedelta(minutes=20)
# About the 98th percentile of a lap over its median in 2024 (ADR 0014).
OUTLIER_FACTOR = Decimal("1.07")
# Held-out error barely moves between 20 and 40, or 5 and 15 (ADR 0014).
MIN_COMPOUND_CLEAN_LAPS = 30
MIN_DRIVER_CLEAN_LAPS = 10


class ExclusionReason(StrEnum):
    NO_DURATION = "no_duration"
    NO_STINT = "no_stint"
    NOT_CALIBRATED_COMPOUND = "not_calibrated_compound"
    FIRST_LAP = "first_lap"
    PIT_OUT_LAP = "pit_out_lap"
    PIT_IN_LAP = "pit_in_lap"
    NO_START_INSTANT = "no_start_instant"
    NEUTRALISED = "neutralised"
    RESTART_LAP = "restart_lap"
    WET_TRACK = "wet_track"
    OUTLIER = "outlier"
    COMPOUND_TOO_FEW_LAPS = "compound_too_few_laps"
    DRIVER_TOO_FEW_LAPS = "driver_too_few_laps"


class CalibrationDataError(ValueError):
    """Race data the model does not describe. Retrying the same input fails the same way."""


@dataclass(frozen=True)
class CleanLap:
    lap: Lap
    lap_duration: Decimal
    tyre: Tyre


@dataclass(frozen=True)
class ExcludedLap:
    lap: Lap
    reason: ExclusionReason


type LapVerdict = CleanLap | ExcludedLap


@dataclass(frozen=True)
class Window:
    """From `start` to `end`; an `end` of None lasts to the end of the race."""

    start: datetime
    end: datetime | None


class RaceRows(Protocol):
    """The clean rows of one race."""

    @property
    def laps(self) -> Sequence[Lap]: ...
    @property
    def stints(self) -> Sequence[Stint]: ...
    @property
    def pits(self) -> Sequence[Pit]: ...
    @property
    def race_control(self) -> Sequence[RaceControl]: ...
    @property
    def weather(self) -> Sequence[Weather]: ...


@dataclass(frozen=True)
class _Race:
    tyres: TyreLookup
    pit_laps: frozenset[tuple[int, int]]
    neutralised_laps: frozenset[tuple[int, int]]
    rain: tuple[Window, ...]


def lap_verdicts(rows: RaceRows) -> tuple[LapVerdict, ...]:
    """One verdict per lap, in driver and lap order."""
    laps = sorted(rows.laps, key=lambda lap: (lap.driver_number, lap.lap_number))
    neutralisations = neutralisation_windows(rows.race_control)
    race = _Race(
        TyreLookup(rows.stints),
        frozenset((pit.driver_number, pit.lap_number) for pit in rows.pits),
        frozenset(_key(lap) for lap in laps if _overlaps_any(lap, neutralisations)),
        rain_windows(rows.weather),
    )
    verdicts = [_on_its_own(lap, race) for lap in laps]
    verdicts = _without_outliers(verdicts)
    verdicts = _without_scarce(
        verdicts, _compound, ExclusionReason.COMPOUND_TOO_FEW_LAPS, MIN_COMPOUND_CLEAN_LAPS
    )
    verdicts = _without_scarce(
        verdicts, _driver, ExclusionReason.DRIVER_TOO_FEW_LAPS, MIN_DRIVER_CLEAN_LAPS
    )
    return tuple(verdicts)


def neutralisation_windows(race_control: Sequence[RaceControl]) -> tuple[Window, ...]:
    """Safety car, virtual safety car and red flag periods, each to the next track clear or
    green flag."""
    windows: list[Window] = []
    start: datetime | None = None
    for row in sorted(race_control, key=lambda row: (row.date, row.seq)):
        opens = _starts_neutralisation(row)
        if start is None and opens:
            start = row.date
        elif start is not None and row.scope == FlagScope.TRACK and row.flag in NEUTRALISATION_ENDS:
            windows.append(Window(start, row.date))
            start = None
    if start is not None:
        windows.append(Window(start, None))
    return tuple(windows)


def rain_windows(weather: Sequence[Weather]) -> tuple[Window, ...]:
    """Each run of rainy readings, to the drying margin after its last one."""
    runs: list[list[datetime]] = []
    dry_before = True
    for reading in sorted(weather, key=lambda reading: reading.date):
        if reading.rainfall and dry_before:
            runs.append([reading.date])
        elif reading.rainfall:
            runs[-1].append(reading.date)
        dry_before = not reading.rainfall
    return tuple(Window(run[0], run[-1] + DRYING_MARGIN) for run in runs)


def _starts_neutralisation(row: RaceControl) -> bool:
    if row.flag == Flag.RED:
        return True
    if row.category != RaceControlCategory.SAFETY_CAR:
        return False
    if row.message in NEUTRALISATION_STARTS:
        return True
    if row.message in NEUTRALISATION_NOTICES:
        return False
    raise CalibrationDataError(f"race_control seq {row.seq}: safety car message {row.message!r}")


type _Rule = Callable[[CleanLap, _Race], bool]

_RULES: tuple[tuple[ExclusionReason, _Rule], ...] = (
    (ExclusionReason.NOT_CALIBRATED_COMPOUND,
     lambda candidate, _: candidate.tyre.compound not in CALIBRATED_COMPOUNDS),
    (ExclusionReason.FIRST_LAP, lambda candidate, _: candidate.lap.lap_number == 1),
    (ExclusionReason.PIT_OUT_LAP, lambda candidate, _: candidate.lap.is_pit_out_lap),
    (ExclusionReason.PIT_IN_LAP, lambda candidate, race: _key(candidate.lap) in race.pit_laps),
    (ExclusionReason.NO_START_INSTANT, lambda candidate, _: candidate.lap.date_start is None),
    (ExclusionReason.NEUTRALISED,
     lambda candidate, race: _key(candidate.lap) in race.neutralised_laps),
    (ExclusionReason.RESTART_LAP,
     lambda candidate, race: _previous(candidate.lap) in race.neutralised_laps),
    (ExclusionReason.WET_TRACK,
     lambda candidate, race: candidate.tyre.compound in DRY_COMPOUNDS
     and _overlaps_any(candidate.lap, race.rain)),
)  # fmt: skip


def _on_its_own(lap: Lap, race: _Race) -> LapVerdict:
    if lap.lap_duration is None:
        return ExcludedLap(lap, ExclusionReason.NO_DURATION)
    tyre = race.tyres.tyre_on(lap)
    if tyre is None:
        return ExcludedLap(lap, ExclusionReason.NO_STINT)
    candidate = CleanLap(lap, lap.lap_duration, tyre)
    reason = next((reason for reason, applies in _RULES if applies(candidate, race)), None)
    return candidate if reason is None else ExcludedLap(lap, reason)


def _without_outliers(verdicts: list[LapVerdict]) -> list[LapVerdict]:
    by_compound: defaultdict[Compound, list[Decimal]] = defaultdict(list)
    for clean in _clean(verdicts):
        by_compound[clean.tyre.compound].append(clean.lap_duration)
    limit = {compound: OUTLIER_FACTOR * median(laps) for compound, laps in by_compound.items()}
    return [
        ExcludedLap(verdict.lap, ExclusionReason.OUTLIER)
        if isinstance(verdict, CleanLap) and verdict.lap_duration > limit[verdict.tyre.compound]
        else verdict
        for verdict in verdicts
    ]


def _without_scarce[K: Hashable](
    verdicts: list[LapVerdict],
    group: Callable[[CleanLap], K],
    reason: ExclusionReason,
    minimum: int,
) -> list[LapVerdict]:
    counts = Counter(group(clean) for clean in _clean(verdicts))
    return [
        ExcludedLap(verdict.lap, reason)
        if isinstance(verdict, CleanLap) and counts[group(verdict)] < minimum
        else verdict
        for verdict in verdicts
    ]


def _compound(clean: CleanLap) -> Compound:
    return clean.tyre.compound


def _driver(clean: CleanLap) -> int:
    return clean.lap.driver_number


def _clean(verdicts: Iterable[LapVerdict]) -> list[CleanLap]:
    return [verdict for verdict in verdicts if isinstance(verdict, CleanLap)]


def _overlaps_any(lap: Lap, windows: Sequence[Window]) -> bool:
    if lap.date_start is None or lap.lap_duration is None:
        return False
    start = lap.date_start
    end = start + timedelta(seconds=float(lap.lap_duration))
    return any(start < (window.end or end) and end > window.start for window in windows)


def _key(lap: Lap) -> tuple[int, int]:
    return lap.driver_number, lap.lap_number


def _previous(lap: Lap) -> tuple[int, int]:
    return lap.driver_number, lap.lap_number - 1
