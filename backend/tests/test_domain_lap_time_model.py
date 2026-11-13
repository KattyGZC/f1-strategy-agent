from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from f1_strategy.domain.clean import Compound
from f1_strategy.domain.clean_laps import ExclusionReason
from f1_strategy.domain.lap_time_model import (
    Calibration,
    CompoundFit,
    DriverPace,
    Exclusion,
    NotCalibrated,
    NotCalibratedReason,
    PredictedLap,
    Rejection,
    StintPlan,
    StintPlanRejectedError,
    TrackTemperature,
    calibrate,
    predict_stint,
)
from tests.replay_rows import Rows
from tests.synthetic_race import (
    DRY,
    T0,
    PlannedStint,
    Truth,
    lap,
    lap_start,
    stint,
    synthetic_race,
    weather,
)

FIRST_LAPS = (Exclusion(ExclusionReason.FIRST_LAP, 2),)


def calibrated(rows: Rows) -> Calibration:
    result = calibrate(rows)
    assert isinstance(result, Calibration)
    return result


def test_a_race_built_from_known_coefficients_gives_them_back() -> None:
    assert calibrate(synthetic_race()) == Calibration(
        race_laps=60,
        compounds=(
            CompoundFit(Compound.SOFT, Decimal("90.2"), Decimal("0.1"), Decimal("-0.06"),
                        Decimal(0), clean_laps=59, min_tyre_age_laps=0, max_tyre_age_laps=29),
            CompoundFit(Compound.HARD, Decimal(91), Decimal("0.04"), Decimal("-0.06"),
                        Decimal(0), clean_laps=59, min_tyre_age_laps=0, max_tyre_age_laps=29),
        ),
        drivers=(DriverPace(1, Decimal("0.3"), 59), DriverPace(44, Decimal("-0.3"), 59)),
        residual_rmse_s=Decimal(0),
        exclusions=FIRST_LAPS,
        track_temperature=TrackTemperature(Decimal(30), Decimal(30), Decimal(30)),
    )  # fmt: skip


WET = Truth(
    base_s={**DRY.base_s, Compound.INTERMEDIATE: Decimal(100)},
    degradation_s_per_lap={**DRY.degradation_s_per_lap, Compound.INTERMEDIATE: Decimal("0.02")},
    progress_s_per_lap={**DRY.progress_s_per_lap, Compound.INTERMEDIATE: Decimal("-0.3")},
    pace_offset_s=DRY.pace_offset_s,
)
WET_PLAN = {
    1: (PlannedStint(Compound.INTERMEDIATE, 1, 20), PlannedStint(Compound.SOFT, 21, 40),
        PlannedStint(Compound.HARD, 41, 60)),
    44: (PlannedStint(Compound.INTERMEDIATE, 1, 25, tyre_age_at_start=3),
         PlannedStint(Compound.HARD, 26, 45), PlannedStint(Compound.SOFT, 46, 60)),
}  # fmt: skip


def test_intermediates_get_their_own_drying_slope() -> None:
    fits = {fit.compound: fit for fit in calibrated(synthetic_race(WET, WET_PLAN)).compounds}

    assert list(fits) == [Compound.SOFT, Compound.HARD, Compound.INTERMEDIATE]
    assert (fits[Compound.INTERMEDIATE].base_s, fits[Compound.INTERMEDIATE].progress_s_per_lap,
            fits[Compound.INTERMEDIATE].degradation_s_per_lap) == (
        Decimal(100), Decimal("-0.3"), Decimal("0.02"))  # fmt: skip
    assert fits[Compound.SOFT].progress_s_per_lap == Decimal("-0.06")


def test_a_race_with_no_clean_lap_is_not_calibrated_and_says_why() -> None:
    rows = Rows(
        laps=[lap(1, 1), lap(1, 2, None)], stints=[stint(1, 1, PlannedStint(Compound.SOFT, 1, 2))]
    )

    assert calibrate(rows) == NotCalibrated(
        NotCalibratedReason.NO_CLEAN_LAPS,
        (Exclusion(ExclusionReason.NO_DURATION, 1), Exclusion(ExclusionReason.FIRST_LAP, 1)),
    )


def test_tyre_age_that_always_moves_with_the_lap_is_not_identifiable() -> None:
    plan = {
        1: (PlannedStint(Compound.HARD, 1, 30),),
        44: (PlannedStint(Compound.HARD, 1, 30),),
    }

    assert calibrate(synthetic_race(DRY, plan)) == NotCalibrated(
        NotCalibratedReason.NOT_IDENTIFIABLE, FIRST_LAPS
    )


NOISE_S = Decimal("0.1")


def noise_s(lap_number: int) -> Decimal:
    """+, -, -, + over each four laps: no mean and no trend inside a block, so it moves no
    coefficient and is exactly the residual."""
    return NOISE_S if (lap_number - 3) % 4 in (0, 3) else -NOISE_S


def test_noise_the_model_cannot_explain_is_its_residual_error() -> None:
    rows = synthetic_race()
    noisy = set(range(3, 31)) | set(range(31, 59))
    rows.laps = [
        replace(one, lap_duration=one.lap_duration + noise_s(one.lap_number))
        if one.lap_duration is not None and one.driver_number == 1 and one.lap_number in noisy
        else one
        for one in rows.laps
    ]

    result, exact = calibrated(rows), calibrated(synthetic_race())

    assert result.residual_rmse_s == Decimal("0.068889")
    assert [fit.residual_rmse_s for fit in result.compounds] == [Decimal("0.068889")] * 2
    assert [replace(fit, residual_rmse_s=Decimal(0)) for fit in result.compounds] == list(
        exact.compounds
    )


def test_readings_outside_the_clean_laps_do_not_count_for_track_temperature() -> None:
    rows = synthetic_race()
    rows.weather = [
        weather(T0, track_c=Decimal(10)),
        weather(lap_start(2), track_c=Decimal(31)),
        weather(lap_start(30), track_c=Decimal(35)),
        weather(lap_start(31), track_c=Decimal(33)),
        weather(lap_start(60), track_c=Decimal(36)),
        weather(lap_start(61), track_c=Decimal(60)),
    ]

    assert calibrated(rows).track_temperature == TrackTemperature(
        Decimal(31), Decimal(34), Decimal(36)
    )


def test_a_race_without_readings_has_no_track_temperature() -> None:
    rows = synthetic_race()
    rows.weather = []

    assert calibrated(rows).track_temperature is None


@given(data=st.data())
def test_the_calibration_does_not_depend_on_the_order_of_the_rows(data: st.DataObject) -> None:
    rows = synthetic_race()
    shuffled = Rows(
        laps=data.draw(st.permutations(rows.laps)),
        stints=data.draw(st.permutations(rows.stints)),
        weather=rows.weather,
    )

    assert calibrate(shuffled) == calibrate(rows)


@given(shift=st.decimals(min_value=-2, max_value=2, places=3))
def test_a_slower_driver_moves_the_offsets_and_not_the_tyre_or_the_track(shift: Decimal) -> None:
    rows = synthetic_race()
    rows.laps = [
        replace(one, lap_duration=one.lap_duration + shift)
        if one.lap_duration is not None and one.driver_number == 1 else one
        for one in rows.laps
    ]  # fmt: skip

    before, after = calibrated(synthetic_race()), calibrated(rows)

    gap = after.drivers[0].pace_offset_s - after.drivers[1].pace_offset_s
    assert gap == before.drivers[0].pace_offset_s - before.drivers[1].pace_offset_s + shift
    assert [(fit.degradation_s_per_lap, fit.progress_s_per_lap) for fit in after.compounds] == [
        (fit.degradation_s_per_lap, fit.progress_s_per_lap) for fit in before.compounds
    ]


MODEL = calibrated(synthetic_race())


def test_a_stint_is_predicted_for_the_average_car() -> None:
    plan = StintPlan(Compound.HARD, tyre_age_at_start_laps=2, start_lap=11, laps=3)

    assert predict_stint(MODEL, plan, None) == (
        PredictedLap(11, 2, Decimal("90.480"), extrapolated=False),
        PredictedLap(12, 3, Decimal("90.460"), extrapolated=False),
        PredictedLap(13, 4, Decimal("90.440"), extrapolated=False),
    )


def test_a_stint_is_predicted_with_the_drivers_pace() -> None:
    plan = StintPlan(Compound.SOFT, tyre_age_at_start_laps=0, start_lap=1, laps=1)

    assert predict_stint(MODEL, plan, 44) == (
        PredictedLap(1, 0, Decimal("89.900"), extrapolated=False),
    )


def test_a_tyre_older_than_any_calibrated_lap_is_flagged_as_extrapolated() -> None:
    plan = StintPlan(Compound.SOFT, tyre_age_at_start_laps=29, start_lap=31, laps=2)

    assert [lap.extrapolated for lap in predict_stint(MODEL, plan, None)] == [False, True]


def test_a_stint_that_ends_on_the_last_lap_is_predicted() -> None:
    plan = StintPlan(Compound.HARD, tyre_age_at_start_laps=0, start_lap=60, laps=1)

    assert [lap.lap_number for lap in predict_stint(MODEL, plan, None)] == [60]


@pytest.mark.parametrize(("plan", "driver", "rejection"), [
    (StintPlan(Compound.SOFT, 0, 10, 0), None, Rejection.ZERO_LAPS),
    (StintPlan(Compound.WET, 0, 10, 5), None, Rejection.COMPOUND_NOT_CALIBRATED),
    (StintPlan(Compound.INTERMEDIATE, 0, 10, 5), None, Rejection.COMPOUND_NOT_CALIBRATED),
    (StintPlan(Compound.MEDIUM, 0, 10, 5), None, Rejection.COMPOUND_NOT_CALIBRATED),
    (StintPlan(Compound.SOFT, 0, 0, 5), None, Rejection.START_BEFORE_LAP_ONE),
    (StintPlan(Compound.SOFT, -1, 10, 5), None, Rejection.NEGATIVE_TYRE_AGE),
    (StintPlan(Compound.SOFT, 0, 60, 2), None, Rejection.PAST_RACE_END),
    (StintPlan(Compound.SOFT, 0, 10, 5), 16, Rejection.DRIVER_NOT_CALIBRATED),
])  # fmt: skip
def test_a_plan_the_calibration_cannot_answer_is_rejected(
    plan: StintPlan, driver: int | None, rejection: Rejection
) -> None:
    with pytest.raises(StintPlanRejectedError, match=f"stint plan rejected: {rejection}") as error:
        predict_stint(MODEL, plan, driver)

    assert error.value.rejection == rejection
