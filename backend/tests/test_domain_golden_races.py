"""Golden cases from 2024 races (ADR 0014, ADR 0015).

Each case is a race winner's last stint with at least 10 clean laps: the race is calibrated
without that stint's laps, the stint is predicted with the winner's pace, and the mean
absolute error over its clean laps must stay within the tolerance. The tolerances are the
90th percentile of that error over every eligible stint of the 2024 races (378 stints, of
which 23 on intermediates; scratch script, 2026-11-12), rounded up to 0.1 s.
"""

import hashlib
from dataclasses import dataclass, replace
from decimal import Decimal

import pytest

from f1_strategy.domain.clean import Compound
from f1_strategy.domain.clean_laps import CleanLap, lap_verdicts
from f1_strategy.domain.lap_time_model import (
    CALIBRATION_VERSION,
    Calibration,
    StintPlan,
    calibrate,
    predict_stint,
)
from f1_strategy.domain.pit_loss import PitLoss
from tests.calibration_races import BAHRAIN, BRITAIN, CANADA, SPAIN, race

DRY_MAE_TOLERANCE_S = Decimal("0.8")
INTERMEDIATE_MAE_TOLERANCE_S = Decimal("1.2")


@dataclass(frozen=True)
class Golden:
    session_key: int
    driver_number: int
    stint_number: int
    compound: Compound
    tolerance_s: Decimal


GOLDEN = (
    Golden(BAHRAIN, 1, 3, Compound.SOFT, DRY_MAE_TOLERANCE_S),
    Golden(SPAIN, 1, 3, Compound.SOFT, DRY_MAE_TOLERANCE_S),
    Golden(CANADA, 1, 3, Compound.MEDIUM, DRY_MAE_TOLERANCE_S),
    Golden(BRITAIN, 1, 2, Compound.INTERMEDIATE, INTERMEDIATE_MAE_TOLERANCE_S),
)


@pytest.mark.parametrize(
    "case", GOLDEN, ids=lambda case: f"{case.session_key}-{case.driver_number}"
)
def test_a_held_out_stint_is_predicted_within_the_tolerance(case: Golden) -> None:
    rows = race(case.session_key)
    stint = next(
        one
        for one in rows.stints
        if (one.driver_number, one.stint_number) == (case.driver_number, case.stint_number)
    )
    assert stint.compound == case.compound
    assert stint.lap_start is not None
    assert stint.lap_end is not None
    held_out = [
        verdict
        for verdict in lap_verdicts(rows)
        if isinstance(verdict, CleanLap)
        and verdict.lap.driver_number == case.driver_number
        and stint.lap_start <= verdict.lap.lap_number <= stint.lap_end
        and verdict.tyre.compound == case.compound
    ]
    held_laps = {verdict.lap.lap_number for verdict in held_out}
    without = replace(rows, laps=[
        lap for lap in rows.laps
        if lap.driver_number != case.driver_number or lap.lap_number not in held_laps
    ])  # fmt: skip
    calibration = calibrate(without)
    assert isinstance(calibration, Calibration)

    plan = StintPlan(
        case.compound, stint.tyre_age_at_start, stint.lap_start, stint.lap_end - stint.lap_start + 1
    )
    predicted = {
        lap.lap_number: lap.lap_time_s
        for lap in predict_stint(calibration, plan, case.driver_number)
    }
    errors = [abs(predicted[verdict.lap.lap_number] - verdict.lap_duration) for verdict in held_out]

    assert len(held_out) >= 10
    assert sum(errors) / len(errors) <= case.tolerance_s


# Pins the calibrations of the fixture races: a change in output without a new
# CALIBRATION_VERSION fails here.
GOLDEN_HASHES = {
    "1": "f05f4368aaef22bc4bf1328ad9711495b5cd76e8ec442274a6e56a44f9f07e05",
    "2": "c5760b805285a9546d7a8c8f44f48de241cf9c88056e14c54a33716a494159e6",
    "3": "9125e8fb34e7db0127e65e78a306942139a76b3ea9eac733de9a0f41683e2d28",
}


def test_the_golden_races_pin_the_calibration_version() -> None:
    digest = hashlib.sha256()
    for session_key in (BAHRAIN, CANADA, SPAIN, BRITAIN):
        digest.update(repr(calibrate(race(session_key))).encode())

    assert GOLDEN_HASHES[CALIBRATION_VERSION] == digest.hexdigest()


# Each race's pit loss as measured over the local 2024 database (scratch script, 2026-11-15),
# where the same rule kept 603 of the season's 825 stops.
GOLDEN_PIT_LOSSES = {
    BAHRAIN: PitLoss(Decimal("24.343"), 42),
    CANADA: PitLoss(Decimal("24.448"), 21),
    SPAIN: PitLoss(Decimal("22.793"), 42),
    BRITAIN: PitLoss(Decimal("24.837"), 43),
}


@pytest.mark.parametrize(("session_key", "pit_loss"), GOLDEN_PIT_LOSSES.items())
def test_a_race_pit_loss_is_the_one_measured_on_the_season(
    session_key: int, pit_loss: PitLoss
) -> None:
    calibration = calibrate(race(session_key))

    assert isinstance(calibration, Calibration)
    assert calibration.pit_loss == pit_loss


# Each race's rain readings as counted over the local 2024 database (make calibrate, 2026-11-16).
GOLDEN_RAIN_READINGS = {BAHRAIN: 0, CANADA: 27, SPAIN: 1, BRITAIN: 37}


@pytest.mark.parametrize(("session_key", "rain_readings"), GOLDEN_RAIN_READINGS.items())
def test_a_race_rain_readings_are_the_ones_counted_on_the_season(
    session_key: int, rain_readings: int
) -> None:
    calibration = calibrate(race(session_key))

    assert isinstance(calibration, Calibration)
    assert calibration.rain_readings == rain_readings
