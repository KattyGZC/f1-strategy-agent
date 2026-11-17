"""Race strategies simulated on one race's calibration (ADR 0017).

Every function here is pure. A strategy is its stints in order: the first starts on lap 1 and
each next one on the lap after the previous ends. Each lap is the lap-time model's prediction
(ADR 0014), and each stop between two stints adds the race's pit loss once (ADR 0015).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from f1_strategy.domain.clean import Compound
from f1_strategy.domain.clean_laps import DRY_COMPOUNDS
from f1_strategy.domain.lap_time_model import (
    Calibration,
    PredictedLap,
    Rejection,
    StintPlan,
    StintPlanRejectedError,
    predict_stint,
)


class StrategyRejection(StrEnum):
    NO_STINTS = "no_stints"
    ZERO_LAPS = "zero_laps"
    NEGATIVE_TYRE_AGE = "negative_tyre_age"
    COMPOUND_NOT_CALIBRATED = "compound_not_calibrated"
    LAPS_DO_NOT_ADD_UP = "laps_do_not_add_up"
    NO_PIT_LOSS = "no_pit_loss"


class Caveat(StrEnum):
    PIT_LOSS_NOT_RELIABLE = "pit_loss_not_reliable"
    EXTRAPOLATED_TYRE_AGE = "extrapolated_tyre_age"
    ONE_DRY_COMPOUND = "one_dry_compound"


class NotModelled(StrEnum):
    STANDING_START = "standing_start"
    STARTING_FUEL = "starting_fuel"
    WIND = "wind"
    DRIVER_AGGRESSIVENESS = "driver_aggressiveness"
    TRACK_TEMPERATURE = "track_temperature"
    RAIN_ON_SLICKS = "rain_on_slicks"


# A stint the model rejects names its strategy's reason; the start is always lap 1 or later and
# the driver is checked before any stint, so their rejections never reach a strategy.
STINT_REJECTIONS = {
    Rejection.ZERO_LAPS: StrategyRejection.ZERO_LAPS,
    Rejection.NEGATIVE_TYRE_AGE: StrategyRejection.NEGATIVE_TYRE_AGE,
    Rejection.COMPOUND_NOT_CALIBRATED: StrategyRejection.COMPOUND_NOT_CALIBRATED,
    Rejection.PAST_RACE_END: StrategyRejection.LAPS_DO_NOT_ADD_UP,
}


class DriverNotCalibratedError(LookupError):
    def __init__(self, driver_number: int) -> None:
        super().__init__(f"driver {driver_number} has no calibrated pace in this race")
        self.driver_number = driver_number


@dataclass(frozen=True)
class StrategyStint:
    compound: Compound
    laps: int
    tyre_age_at_start_laps: int


@dataclass(frozen=True)
class SimulatedStint:
    compound: Compound
    laps: tuple[PredictedLap, ...]


@dataclass(frozen=True)
class Stop:
    in_lap: int
    pit_loss_s: Decimal


@dataclass(frozen=True)
class Simulated:
    stints: tuple[SimulatedStint, ...]
    stops: tuple[Stop, ...]
    total_s: Decimal
    gap_to_fastest_s: Decimal
    caveats: tuple[Caveat, ...]


@dataclass(frozen=True)
class Rejected:
    reason: StrategyRejection
    # None when the reason is the strategy's as a whole.
    stint_number: int | None


type StrategyResult = Simulated | Rejected


@dataclass(frozen=True)
class _Run:
    stints: tuple[SimulatedStint, ...]
    stops: tuple[Stop, ...]
    caveats: tuple[Caveat, ...]

    @property
    def total_s(self) -> Decimal:
        laps_s = sum((lap.lap_time_s for stint in self.stints for lap in stint.laps), Decimal(0))
        return laps_s + sum((stop.pit_loss_s for stop in self.stops), Decimal(0))


def simulate(
    calibration: Calibration,
    strategies: Sequence[Sequence[StrategyStint]],
    driver_number: int | None,
) -> tuple[StrategyResult, ...]:
    """Each strategy for a driver or, with None, for the average car of the race."""
    _check_driver(calibration, driver_number)
    runs = [_run(calibration, stints, driver_number) for stints in strategies]
    totals_s = [run.total_s for run in runs if isinstance(run, _Run)]
    return tuple(
        run if isinstance(run, Rejected) else _simulated(run, min(totals_s)) for run in runs
    )


def not_modelled(calibration: Calibration) -> tuple[NotModelled, ...]:
    """What every simulation of the race leaves out (ADR 0017)."""
    return tuple(
        member
        for member in NotModelled
        if member != NotModelled.RAIN_ON_SLICKS or calibration.rain_readings
    )


def _check_driver(calibration: Calibration, driver_number: int | None) -> None:
    calibrated = {pace.driver_number for pace in calibration.drivers}
    if driver_number is not None and driver_number not in calibrated:
        raise DriverNotCalibratedError(driver_number)


def _run(
    calibration: Calibration, stints: Sequence[StrategyStint], driver_number: int | None
) -> _Run | Rejected:
    if not stints:
        return Rejected(StrategyRejection.NO_STINTS, None)
    simulated: list[SimulatedStint] = []
    start_lap = 1
    for number, stint in enumerate(stints, start=1):
        plan = StintPlan(stint.compound, stint.tyre_age_at_start_laps, start_lap, stint.laps)
        try:
            laps = predict_stint(calibration, plan, driver_number)
        except StintPlanRejectedError as rejected:
            return Rejected(STINT_REJECTIONS[rejected.rejection], number)
        simulated.append(SimulatedStint(stint.compound, laps))
        start_lap += stint.laps
    if start_lap - 1 != calibration.race_laps:
        return Rejected(StrategyRejection.LAPS_DO_NOT_ADD_UP, None)
    return _with_stops(calibration, tuple(simulated))


def _with_stops(calibration: Calibration, stints: tuple[SimulatedStint, ...]) -> _Run | Rejected:
    in_laps = [stint.laps[-1].lap_number for stint in stints[:-1]]
    if not in_laps:
        return _Run(stints, (), _caveats(stints, stops_pit_loss_reliable=True))
    pit_loss = calibration.pit_loss
    if pit_loss is None:
        return Rejected(StrategyRejection.NO_PIT_LOSS, None)
    stops = tuple(Stop(in_lap, pit_loss.pit_loss_s) for in_lap in in_laps)
    return _Run(stints, stops, _caveats(stints, stops_pit_loss_reliable=pit_loss.reliable))


def _caveats(
    stints: Sequence[SimulatedStint], *, stops_pit_loss_reliable: bool
) -> tuple[Caveat, ...]:
    applies = {
        Caveat.PIT_LOSS_NOT_RELIABLE: not stops_pit_loss_reliable,
        Caveat.EXTRAPOLATED_TYRE_AGE: _any_extrapolated(stints),
        Caveat.ONE_DRY_COMPOUND: _one_dry_compound(stints),
    }
    return tuple(caveat for caveat in Caveat if applies[caveat])


def _any_extrapolated(stints: Sequence[SimulatedStint]) -> bool:
    return any(lap.extrapolated for stint in stints for lap in stint.laps)


def _one_dry_compound(stints: Sequence[SimulatedStint]) -> bool:
    compounds = {stint.compound for stint in stints}
    return len(compounds) == 1 and compounds.pop() in DRY_COMPOUNDS


def _simulated(run: _Run, fastest_s: Decimal) -> Simulated:
    total_s = run.total_s
    return Simulated(run.stints, run.stops, total_s, total_s - fastest_s, run.caveats)
