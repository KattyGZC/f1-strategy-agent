from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from f1_strategy.domain.clean import Compound
from f1_strategy.domain.lap_time_model import Calibration, CompoundFit, DriverPace, PredictedLap
from f1_strategy.domain.pit_loss import PitLoss
from f1_strategy.domain.strategy import (
    Caveat,
    DriverNotCalibratedError,
    NotModelled,
    Rejected,
    Simulated,
    SimulatedStint,
    Stop,
    StrategyRejection,
    StrategyStint,
    not_modelled,
    simulate,
)

DRIVER = 1
# SOFT: 90 + 0.1 * age - 0.05 * (lap - 1); HARD: 91 + 0.05 * age - 0.05 * (lap - 1).
CALIBRATION = Calibration(
    race_laps=10,
    compounds=(
        CompoundFit(Compound.SOFT, Decimal(90), Decimal("0.1"), Decimal("-0.05"), Decimal("0.4"),
                    clean_laps=40, min_tyre_age_laps=1, max_tyre_age_laps=5),
        CompoundFit(Compound.HARD, Decimal(91), Decimal("0.05"), Decimal("-0.05"), Decimal("0.4"),
                    clean_laps=40, min_tyre_age_laps=1, max_tyre_age_laps=8),
    ),
    drivers=(DriverPace(DRIVER, Decimal("0.3"), 40), DriverPace(44, Decimal("-0.3"), 40)),
    residual_rmse_s=Decimal("0.4"),
    exclusions=(),
    track_temperature=None,
    rain_readings=0,
    pit_loss=PitLoss(Decimal("20.000"), stops=10),
    pit_stop_exclusions=(),
)  # fmt: skip
SOFT_THEN_HARD = (StrategyStint(Compound.SOFT, 4, 0), StrategyStint(Compound.HARD, 6, 0))
HARD_ONLY = (StrategyStint(Compound.HARD, 10, 0),)


def lap(lap_number: int, age: int, lap_time_s: str, *, extrapolated: bool = False) -> PredictedLap:
    return PredictedLap(lap_number, age, Decimal(lap_time_s), extrapolated)


def test_a_one_stop_strategy_is_its_laps_plus_one_pit_loss() -> None:
    assert simulate(CALIBRATION, [SOFT_THEN_HARD], None) == (
        Simulated(
            stints=(
                SimulatedStint(Compound.SOFT, (
                    lap(1, 0, "90.000", extrapolated=True), lap(2, 1, "90.050"),
                    lap(3, 2, "90.100"), lap(4, 3, "90.150"),
                )),
                SimulatedStint(Compound.HARD, (
                    lap(5, 0, "90.800", extrapolated=True), lap(6, 1, "90.800"),
                    lap(7, 2, "90.800"), lap(8, 3, "90.800"), lap(9, 4, "90.800"),
                    lap(10, 5, "90.800"),
                )),
            ),
            stops=(Stop(in_lap=4, pit_loss_s=Decimal("20.000")),),
            total_s=Decimal("925.100"),
            gap_to_fastest_s=Decimal("0.000"),
            caveats=(Caveat.EXTRAPOLATED_TYRE_AGE,),
        ),
    )  # fmt: skip


def test_a_drivers_pace_moves_every_lap_and_not_the_stops() -> None:
    (average,) = simulate(CALIBRATION, [SOFT_THEN_HARD], None)
    (driver,) = simulate(CALIBRATION, [SOFT_THEN_HARD], DRIVER)

    assert isinstance(average, Simulated)
    assert isinstance(driver, Simulated)
    assert driver.total_s - average.total_s == Decimal("3.000")
    assert driver.stops == average.stops


def test_each_strategy_is_timed_against_the_fastest() -> None:
    one_stop, no_stop = simulate(CALIBRATION, [SOFT_THEN_HARD, HARD_ONLY], None)

    assert isinstance(one_stop, Simulated)
    assert isinstance(no_stop, Simulated)
    assert (no_stop.total_s, no_stop.gap_to_fastest_s) == (Decimal("910.000"), Decimal("0.000"))
    assert (one_stop.total_s, one_stop.gap_to_fastest_s) == (Decimal("925.100"), Decimal("15.100"))
    assert no_stop.stops == ()
    assert no_stop.caveats == (Caveat.EXTRAPOLATED_TYRE_AGE, Caveat.ONE_DRY_COMPOUND)


def test_a_stop_to_the_same_compound_is_a_new_set_of_it() -> None:
    (result,) = simulate(
        CALIBRATION,
        [(StrategyStint(Compound.HARD, 5, 1), StrategyStint(Compound.HARD, 5, 1))],
        None,
    )

    assert isinstance(result, Simulated)
    assert [stint.laps[0].tyre_age_laps for stint in result.stints] == [1, 1]
    assert result.stops == (Stop(5, Decimal("20.000")),)
    assert result.caveats == (Caveat.ONE_DRY_COMPOUND,)


def test_a_stop_on_the_last_lap_but_one_leaves_a_one_lap_stint() -> None:
    (result,) = simulate(
        CALIBRATION,
        [(StrategyStint(Compound.HARD, 9, 1), StrategyStint(Compound.SOFT, 1, 1))],
        None,
    )

    assert isinstance(result, Simulated)
    assert result.stints[1] == SimulatedStint(Compound.SOFT, (lap(10, 1, "89.650"),))
    assert result.stops == (Stop(9, Decimal("20.000")),)


@pytest.mark.parametrize(
    ("stints", "rejected"),
    [
        pytest.param((), Rejected(StrategyRejection.NO_STINTS, None), id="no stints"),
        pytest.param(
            (StrategyStint(Compound.SOFT, 10, 0), StrategyStint(Compound.HARD, 0, 0)),
            Rejected(StrategyRejection.ZERO_LAPS, 2),
            id="a stint of zero laps",
        ),
        pytest.param(
            (StrategyStint(Compound.SOFT, 4, -1), StrategyStint(Compound.HARD, 6, 0)),
            Rejected(StrategyRejection.NEGATIVE_TYRE_AGE, 1),
            id="a negative tyre age",
        ),
        pytest.param(
            (StrategyStint(Compound.SOFT, 4, 0), StrategyStint(Compound.MEDIUM, 6, 0)),
            Rejected(StrategyRejection.COMPOUND_NOT_CALIBRATED, 2),
            id="a compound the race did not calibrate",
        ),
        pytest.param(
            (StrategyStint(Compound.INTERMEDIATE, 10, 0),),
            Rejected(StrategyRejection.COMPOUND_NOT_CALIBRATED, 1),
            id="intermediates in a dry race",
        ),
        pytest.param(
            (StrategyStint(Compound.SOFT, 4, 0), StrategyStint(Compound.HARD, 5, 0)),
            Rejected(StrategyRejection.LAPS_DO_NOT_ADD_UP, None),
            id="short of the race",
        ),
        pytest.param(
            (StrategyStint(Compound.SOFT, 4, 0), StrategyStint(Compound.HARD, 7, 0)),
            Rejected(StrategyRejection.LAPS_DO_NOT_ADD_UP, 2),
            id="past the race",
        ),
    ],
)
def test_a_strategy_the_race_cannot_run_is_rejected_with_its_stint(
    stints: tuple[StrategyStint, ...], rejected: Rejected
) -> None:
    assert simulate(CALIBRATION, [stints], None) == (rejected,)


def test_a_rejected_strategy_does_not_move_the_others() -> None:
    alone = simulate(CALIBRATION, [SOFT_THEN_HARD], None)

    results = simulate(CALIBRATION, [(), SOFT_THEN_HARD], None)

    assert results == (Rejected(StrategyRejection.NO_STINTS, None), *alone)


def test_every_strategy_can_be_rejected() -> None:
    no_stints = Rejected(StrategyRejection.NO_STINTS, None)

    assert simulate(CALIBRATION, [(), ()], None) == (no_stints, no_stints)


def test_no_strategies_simulate_to_no_results() -> None:
    assert simulate(CALIBRATION, [], None) == ()


def test_a_race_without_a_pit_loss_rejects_a_stop_and_runs_a_strategy_without_one() -> None:
    calibration = replace(CALIBRATION, pit_loss=None)

    one_stop, no_stop = simulate(calibration, [SOFT_THEN_HARD, HARD_ONLY], None)

    assert one_stop == Rejected(StrategyRejection.NO_PIT_LOSS, None)
    assert isinstance(no_stop, Simulated)
    assert no_stop.total_s == Decimal("910.000")


def test_a_pit_loss_not_reliable_is_named_only_where_the_strategy_stops() -> None:
    calibration = replace(CALIBRATION, pit_loss=PitLoss(Decimal("20.000"), stops=1))

    one_stop, no_stop = simulate(calibration, [SOFT_THEN_HARD, HARD_ONLY], None)

    assert isinstance(one_stop, Simulated)
    assert isinstance(no_stop, Simulated)
    assert one_stop.caveats == (Caveat.PIT_LOSS_NOT_RELIABLE, Caveat.EXTRAPOLATED_TYRE_AGE)
    assert Caveat.PIT_LOSS_NOT_RELIABLE not in no_stop.caveats


def test_tyres_within_the_calibrated_ages_carry_no_caveat() -> None:
    (result,) = simulate(
        CALIBRATION,
        [(StrategyStint(Compound.SOFT, 4, 1), StrategyStint(Compound.HARD, 6, 1))],
        None,
    )

    assert isinstance(result, Simulated)
    assert result.caveats == ()


def test_intermediates_alone_are_not_one_dry_compound() -> None:
    wet = CompoundFit(Compound.INTERMEDIATE, Decimal(100), Decimal(0), Decimal(0), Decimal(1),
                      clean_laps=40, min_tyre_age_laps=0, max_tyre_age_laps=20)  # fmt: skip
    calibration = replace(CALIBRATION, compounds=(wet,))

    (result,) = simulate(calibration, [(StrategyStint(Compound.INTERMEDIATE, 10, 0),)], None)

    assert isinstance(result, Simulated)
    assert result.caveats == ()


@pytest.mark.parametrize("strategies", [[], [SOFT_THEN_HARD]], ids=["no strategy", "one"])
def test_a_driver_without_a_calibrated_pace_refuses_the_whole_simulation(
    strategies: list[tuple[StrategyStint, ...]],
) -> None:
    with pytest.raises(DriverNotCalibratedError) as refused:
        simulate(CALIBRATION, strategies, 99)

    assert refused.value.driver_number == 99
    assert str(refused.value) == "driver 99 has no calibrated pace in this race"


def test_a_dry_race_leaves_out_the_start_fuel_wind_aggressiveness_and_temperature() -> None:
    assert not_modelled(CALIBRATION) == (
        NotModelled.STANDING_START,
        NotModelled.STARTING_FUEL,
        NotModelled.WIND,
        NotModelled.DRIVER_AGGRESSIVENESS,
        NotModelled.TRACK_TEMPERATURE,
    )


def test_a_race_with_rain_also_leaves_out_rain_on_slicks() -> None:
    assert not_modelled(replace(CALIBRATION, rain_readings=1)) == (
        *not_modelled(CALIBRATION),
        NotModelled.RAIN_ON_SLICKS,
    )


stint_choices = st.builds(
    StrategyStint,
    compound=st.sampled_from([Compound.SOFT, Compound.MEDIUM, Compound.HARD]),
    laps=st.integers(min_value=0, max_value=6),
    tyre_age_at_start_laps=st.integers(min_value=-1, max_value=12),
)
strategy_lists = st.lists(st.lists(stint_choices, max_size=4), max_size=4)


@given(strategies=strategy_lists, data=st.data())
def test_a_strategys_result_does_not_depend_on_where_it_is_in_the_request(
    strategies: list[list[StrategyStint]], data: st.DataObject
) -> None:
    order = data.draw(st.permutations(range(len(strategies))))

    results = simulate(CALIBRATION, strategies, DRIVER)
    reordered = simulate(CALIBRATION, [strategies[i] for i in order], DRIVER)

    assert reordered == tuple(results[i] for i in order)
    assert simulate(CALIBRATION, strategies, DRIVER) == results


@given(strategies=strategy_lists)
def test_a_total_is_its_laps_and_stops_and_the_fastest_has_no_gap(
    strategies: list[list[StrategyStint]],
) -> None:
    simulated = [r for r in simulate(CALIBRATION, strategies, None) if isinstance(r, Simulated)]

    for result in simulated:
        laps_s = sum(lap.lap_time_s for stint in result.stints for lap in stint.laps)
        assert result.total_s == laps_s + sum(stop.pit_loss_s for stop in result.stops)
        assert len(result.stops) == len(result.stints) - 1
        assert result.gap_to_fastest_s >= 0
    if simulated:
        assert min(result.gap_to_fastest_s for result in simulated) == 0
