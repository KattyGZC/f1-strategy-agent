"""The lap-time model of one race, calibrated on its clean laps, and its predictions (ADR 0014).

Every function here is pure. For driver d on compound c at tyre age a on lap l:

    lap_time_s = base_s[c] + pace_offset_s[d] + degradation_s_per_lap[c] * a
                 + progress_s_per_lap[c] * (l - 1)

The dry compounds share one progress slope (fuel burn and track evolution together);
INTERMEDIATE has its own, since the track dries while it runs. Driver offsets average zero,
so the base is the average car of the race.
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from statistics import mean, median

from f1_strategy.domain.clean import Compound, Weather
from f1_strategy.domain.clean_laps import (
    CALIBRATED_COMPOUNDS,
    DRY_COMPOUNDS,
    CleanLap,
    ExclusionReason,
    LapVerdict,
    RaceRows,
    lap_verdicts,
)
from f1_strategy.domain.least_squares import SingularSystemError, least_squares

# Raise whenever the calibration of the same clean rows changes, thresholds included.
CALIBRATION_VERSION = "1"

COEFFICIENT_DECIMALS = 6
COEFFICIENT_SCALE = 10**COEFFICIENT_DECIMALS
COEFFICIENT_STEP = Decimal(1).scaleb(-COEFFICIENT_DECIMALS)
LAP_TIME_STEP = Decimal("0.001")


class NotCalibratedReason(StrEnum):
    NO_CLEAN_LAPS = "no_clean_laps"
    NOT_IDENTIFIABLE = "not_identifiable"


class Rejection(StrEnum):
    ZERO_LAPS = "zero_laps"
    COMPOUND_NOT_CALIBRATED = "compound_not_calibrated"
    START_BEFORE_LAP_ONE = "start_before_lap_one"
    NEGATIVE_TYRE_AGE = "negative_tyre_age"
    PAST_RACE_END = "past_race_end"
    DRIVER_NOT_CALIBRATED = "driver_not_calibrated"


class StintPlanRejectedError(ValueError):
    def __init__(self, rejection: Rejection) -> None:
        super().__init__(f"stint plan rejected: {rejection}")
        self.rejection = rejection


@dataclass(frozen=True)
class CompoundFit:
    compound: Compound
    base_s: Decimal
    degradation_s_per_lap: Decimal
    progress_s_per_lap: Decimal
    residual_rmse_s: Decimal
    clean_laps: int
    min_tyre_age_laps: int
    max_tyre_age_laps: int


@dataclass(frozen=True)
class DriverPace:
    driver_number: int
    pace_offset_s: Decimal
    clean_laps: int


@dataclass(frozen=True)
class Exclusion:
    reason: ExclusionReason
    laps: int


@dataclass(frozen=True)
class TrackTemperature:
    min_c: Decimal
    median_c: Decimal
    max_c: Decimal


@dataclass(frozen=True)
class Calibration:
    race_laps: int
    compounds: tuple[CompoundFit, ...]
    drivers: tuple[DriverPace, ...]
    residual_rmse_s: Decimal
    exclusions: tuple[Exclusion, ...]
    track_temperature: TrackTemperature | None


@dataclass(frozen=True)
class NotCalibrated:
    reason: NotCalibratedReason
    exclusions: tuple[Exclusion, ...]


@dataclass(frozen=True)
class StintPlan:
    compound: Compound
    tyre_age_at_start_laps: int
    start_lap: int
    laps: int


@dataclass(frozen=True)
class PredictedLap:
    lap_number: int
    tyre_age_laps: int
    lap_time_s: Decimal
    extrapolated: bool


type _Column = Callable[[CleanLap], Fraction]


def calibrate(rows: RaceRows) -> Calibration | NotCalibrated:
    verdicts = lap_verdicts(rows)
    exclusions = _exclusions(verdicts)
    clean = [verdict for verdict in verdicts if isinstance(verdict, CleanLap)]
    if not clean:
        return NotCalibrated(NotCalibratedReason.NO_CLEAN_LAPS, exclusions)
    compounds = [compound for compound in CALIBRATED_COMPOUNDS if _runs(clean, compound)]
    columns = _columns(compounds)
    try:
        coefficients = least_squares(*_within_drivers(clean, columns))
    except SingularSystemError:
        return NotCalibrated(NotCalibratedReason.NOT_IDENTIFIABLE, exclusions)
    return _calibration(rows, clean, compounds, coefficients, exclusions)


def predict_stint(
    calibration: Calibration, plan: StintPlan, driver_number: int | None
) -> tuple[PredictedLap, ...]:
    """The stint's lap times, for a driver or, with None, for the average car of the race."""
    fit = _checked_fit(calibration, plan)
    offset_s = _pace_offset_s(calibration, driver_number)
    return tuple(
        _predicted(fit, offset_s, plan.start_lap + i, plan.tyre_age_at_start_laps + i)
        for i in range(plan.laps)
    )


def _checked_fit(calibration: Calibration, plan: StintPlan) -> CompoundFit:
    if plan.laps < 1:
        raise StintPlanRejectedError(Rejection.ZERO_LAPS)
    fit = next((fit for fit in calibration.compounds if fit.compound == plan.compound), None)
    if fit is None:
        raise StintPlanRejectedError(Rejection.COMPOUND_NOT_CALIBRATED)
    if plan.start_lap < 1:
        raise StintPlanRejectedError(Rejection.START_BEFORE_LAP_ONE)
    if plan.tyre_age_at_start_laps < 0:
        raise StintPlanRejectedError(Rejection.NEGATIVE_TYRE_AGE)
    if plan.start_lap + plan.laps - 1 > calibration.race_laps:
        raise StintPlanRejectedError(Rejection.PAST_RACE_END)
    return fit


def _pace_offset_s(calibration: Calibration, driver_number: int | None) -> Decimal:
    if driver_number is None:
        return Decimal(0)
    pace = next((d for d in calibration.drivers if d.driver_number == driver_number), None)
    if pace is None:
        raise StintPlanRejectedError(Rejection.DRIVER_NOT_CALIBRATED)
    return pace.pace_offset_s


def _predicted(fit: CompoundFit, offset_s: Decimal, lap_number: int, age: int) -> PredictedLap:
    lap_time_s = (
        fit.base_s
        + offset_s
        + fit.degradation_s_per_lap * age
        + fit.progress_s_per_lap * (lap_number - 1)
    )
    calibrated = fit.min_tyre_age_laps <= age <= fit.max_tyre_age_laps
    return PredictedLap(
        lap_number,
        age,
        lap_time_s.quantize(LAP_TIME_STEP),
        extrapolated=not calibrated,
    )


def _runs(clean: Sequence[CleanLap], compound: Compound) -> bool:
    return any(lap.tyre.compound == compound for lap in clean)


def _columns(compounds: Sequence[Compound]) -> tuple[_Column, ...]:
    """Base offsets relative to the first compound (driver offsets absorb the level), one
    degradation slope per compound, and the progress slopes."""
    bases = [_indicator(compound) for compound in compounds[1:]]
    slopes = [_degradation(compound) for compound in compounds]
    progress = [_progress(group) for group in _progress_groups(compounds)]
    return (*bases, *slopes, *progress)


def _progress_groups(compounds: Sequence[Compound]) -> list[tuple[Compound, ...]]:
    """The compounds that share a progress slope, among those the race calibrates."""
    groups = (DRY_COMPOUNDS, (Compound.INTERMEDIATE,))
    return [group for group in groups if any(compound in group for compound in compounds)]


def _indicator(compound: Compound) -> _Column:
    return lambda lap: Fraction(int(lap.tyre.compound == compound))


def _degradation(compound: Compound) -> _Column:
    return lambda lap: Fraction(lap.tyre.age_laps if lap.tyre.compound == compound else 0)


def _progress(group: tuple[Compound, ...]) -> _Column:
    return lambda lap: Fraction(lap.lap.lap_number - 1 if lap.tyre.compound in group else 0)


def _within_drivers(
    clean: Sequence[CleanLap], columns: Sequence[_Column]
) -> tuple[list[list[Fraction]], list[Fraction]]:
    """Each column and the lap time minus its driver's mean: the fit then holds for any
    driver offsets. The lap time is the last value of each row."""
    raw = [
        (lap.lap.driver_number, [*(column(lap) for column in columns), Fraction(lap.lap_duration)])
        for lap in clean
    ]
    means = _driver_means(raw)
    demeaned = [
        [value - means[driver][i] for i, value in enumerate(values)] for driver, values in raw
    ]
    return [row[:-1] for row in demeaned], [row[-1] for row in demeaned]


def _driver_means(raw: Sequence[tuple[int, list[Fraction]]]) -> dict[int, list[Fraction]]:
    by_driver: defaultdict[int, list[list[Fraction]]] = defaultdict(list)
    for driver, values in raw:
        by_driver[driver].append(values)
    return {
        driver: [mean(values[i] for values in rows) for i in range(len(rows[0]))]
        for driver, rows in by_driver.items()
    }


def _calibration(
    rows: RaceRows,
    clean: Sequence[CleanLap],
    compounds: Sequence[Compound],
    coefficients: Sequence[Fraction],
    exclusions: tuple[Exclusion, ...],
) -> Calibration:
    model = _Model(compounds, coefficients)
    level = _driver_levels(clean, model)
    mean_level = mean(level.values())
    residuals = [
        Fraction(lap.lap_duration) - level[lap.lap.driver_number] - model.without_driver(lap)
        for lap in clean
    ]
    fits = tuple(
        _compound_fit(compound, model, mean_level, clean, residuals) for compound in compounds
    )
    drivers = tuple(
        DriverPace(driver, _decimal(level[driver] - mean_level), count)
        for driver, count in sorted(Counter(lap.lap.driver_number for lap in clean).items())
    )
    return Calibration(
        race_laps=max(lap.lap_number for lap in rows.laps),
        compounds=fits,
        drivers=drivers,
        residual_rmse_s=_rmse(residuals),
        exclusions=exclusions,
        track_temperature=_track_temperature(clean, rows.weather),
    )


@dataclass(frozen=True)
class _Model:
    compounds: Sequence[Compound]
    coefficients: Sequence[Fraction]

    def base(self, compound: Compound) -> Fraction:
        index = list(self.compounds).index(compound)
        return Fraction(0) if index == 0 else self.coefficients[index - 1]

    def degradation(self, compound: Compound) -> Fraction:
        bases = len(self.compounds) - 1
        return self.coefficients[bases + list(self.compounds).index(compound)]

    def progress(self, compound: Compound) -> Fraction:
        first = 2 * len(self.compounds) - 1
        groups = _progress_groups(self.compounds)
        index = next(i for i, group in enumerate(groups) if compound in group)
        return self.coefficients[first + index]

    def without_driver(self, lap: CleanLap) -> Fraction:
        compound = lap.tyre.compound
        return (
            self.base(compound)
            + self.degradation(compound) * lap.tyre.age_laps
            + self.progress(compound) * (lap.lap.lap_number - 1)
        )


def _driver_levels(clean: Sequence[CleanLap], model: _Model) -> dict[int, Fraction]:
    gaps: defaultdict[int, list[Fraction]] = defaultdict(list)
    for lap in clean:
        gaps[lap.lap.driver_number].append(Fraction(lap.lap_duration) - model.without_driver(lap))
    return {driver: mean(values) for driver, values in gaps.items()}


def _compound_fit(
    compound: Compound,
    model: _Model,
    mean_level: Fraction,
    clean: Sequence[CleanLap],
    residuals: Sequence[Fraction],
) -> CompoundFit:
    on_compound = [i for i, lap in enumerate(clean) if lap.tyre.compound == compound]
    ages = [clean[i].tyre.age_laps for i in on_compound]
    return CompoundFit(
        compound=compound,
        base_s=_decimal(model.base(compound) + mean_level),
        degradation_s_per_lap=_decimal(model.degradation(compound)),
        progress_s_per_lap=_decimal(model.progress(compound)),
        residual_rmse_s=_rmse([residuals[i] for i in on_compound]),
        clean_laps=len(on_compound),
        min_tyre_age_laps=min(ages),
        max_tyre_age_laps=max(ages),
    )


def _exclusions(verdicts: Sequence[LapVerdict]) -> tuple[Exclusion, ...]:
    counts = Counter(verdict.reason for verdict in verdicts if not isinstance(verdict, CleanLap))
    return tuple(Exclusion(reason, counts[reason]) for reason in ExclusionReason if counts[reason])


def _track_temperature(
    clean: Sequence[CleanLap], weather: Sequence[Weather]
) -> TrackTemperature | None:
    """Over the readings from the first clean lap's start to the last one's."""
    starts = [lap.lap.date_start for lap in clean if lap.lap.date_start is not None]
    first, last = min(starts), max(starts)
    readings = [reading.track_temperature for reading in weather if first <= reading.date <= last]
    if not readings:
        return None
    return TrackTemperature(min(readings), median(readings), max(readings))


def _rmse(residuals: Sequence[Fraction]) -> Decimal:
    mean_square = mean(r * r for r in residuals)
    root = (Decimal(mean_square.numerator) / Decimal(mean_square.denominator)).sqrt()
    return root.quantize(COEFFICIENT_STEP)


def _decimal(value: Fraction) -> Decimal:
    """Rounded half to even, exactly: `round` of a fraction does not go through floats."""
    return Decimal(round(value * COEFFICIENT_SCALE)).scaleb(-COEFFICIENT_DECIMALS)
