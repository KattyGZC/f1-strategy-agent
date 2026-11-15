"""The time a pit stop costs in one race, measured on its own stops (ADR 0015).

Every function here is pure. A stop on lap n (its in-lap; lap n + 1 is its out-lap) costs

    (lap n + lap n + 1) - (lap n - 1 + lap n + 2)

of the same driver, and the race's pit loss is the median over its usable stops.
"""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from statistics import median

from f1_strategy.domain.clean import Lap, Pit
from f1_strategy.domain.clean_laps import RaceRows, Window, neutralisation_windows, overlaps_any

PIT_LOSS_STEP = Decimal("0.001")
# Below it a race still has its pit loss, marked as not reliable (ADR 0015).
MIN_RELIABLE_PIT_STOPS = 5


class PitStopExclusionReason(StrEnum):
    REFERENCE_IS_FIRST_LAP = "reference_is_first_lap"
    MISSING_LAP = "missing_lap"
    UNTIMED_LAP = "untimed_lap"
    NEXT_TO_ANOTHER_STOP = "next_to_another_stop"
    NEUTRALISED = "neutralised"


@dataclass(frozen=True)
class PitStopExclusion:
    reason: PitStopExclusionReason
    stops: int


@dataclass(frozen=True)
class PitLoss:
    pit_loss_s: Decimal
    stops: int

    @property
    def reliable(self) -> bool:
        return self.stops >= MIN_RELIABLE_PIT_STOPS


@dataclass(frozen=True)
class PitLossMeasurement:
    """None when no stop of the race is usable."""

    pit_loss: PitLoss | None
    exclusions: tuple[PitStopExclusion, ...]


@dataclass(frozen=True)
class _Race:
    laps: dict[tuple[int, int], Lap]
    pit_laps: frozenset[tuple[int, int]]
    neutralisations: tuple[Window, ...]


def measure_pit_loss(rows: RaceRows) -> PitLossMeasurement:
    race = _Race(
        {(lap.driver_number, lap.lap_number): lap for lap in rows.laps},
        frozenset((pit.driver_number, pit.lap_number) for pit in rows.pits),
        neutralisation_windows(rows.race_control),
    )
    losses: list[Decimal] = []
    excluded: Counter[PitStopExclusionReason] = Counter()
    for pit in rows.pits:
        verdict = _stop_loss(pit, race)
        if isinstance(verdict, PitStopExclusionReason):
            excluded[verdict] += 1
        else:
            losses.append(verdict)
    exclusions = tuple(
        PitStopExclusion(reason, excluded[reason])
        for reason in PitStopExclusionReason
        if excluded[reason]
    )
    if not losses:
        return PitLossMeasurement(None, exclusions)
    return PitLossMeasurement(
        PitLoss(median(losses).quantize(PIT_LOSS_STEP), len(losses)), exclusions
    )


def _stop_loss(pit: Pit, race: _Race) -> Decimal | PitStopExclusionReason:
    """The stop's loss, or the first reason in `PitStopExclusionReason` order that excludes it."""
    driver, n = pit.driver_number, pit.lap_number
    if n - 1 <= 1:
        return PitStopExclusionReason.REFERENCE_IS_FIRST_LAP
    found = [race.laps.get((driver, number)) for number in (n - 1, n, n + 1, n + 2)]
    laps = [lap for lap in found if lap is not None]
    if len(laps) < len(found):
        return PitStopExclusionReason.MISSING_LAP
    durations = [lap.lap_duration for lap in laps if lap.date_start is not None]
    timed = [duration for duration in durations if duration is not None]
    if len(timed) < len(laps):
        return PitStopExclusionReason.UNTIMED_LAP
    if _next_to_another_stop(driver, n, laps[0], race):
        return PitStopExclusionReason.NEXT_TO_ANOTHER_STOP
    if any(overlaps_any(lap, race.neutralisations) for lap in laps):
        return PitStopExclusionReason.NEUTRALISED
    before, in_lap, out_lap, after = timed
    return in_lap + out_lap - before - after


def _next_to_another_stop(driver: int, n: int, before: Lap, race: _Race) -> bool:
    neighbours = (n - 2, n - 1, n + 1, n + 2)
    return before.is_pit_out_lap or any((driver, lap) in race.pit_laps for lap in neighbours)
