from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from f1_strategy.domain.clean import Flag, Lap
from f1_strategy.domain.pit_loss import (
    MIN_RELIABLE_PIT_STOPS,
    PitLoss,
    PitLossMeasurement,
    PitStopExclusion,
    PitStopExclusionReason,
    measure_pit_loss,
)
from tests.replay_rows import Rows
from tests.synthetic_race import lap, lap_start, pit, race_control, track_flag, weather

STOP_LAPS = (Decimal(90), Decimal(112), Decimal(101), Decimal(90))


def stop(rows: Rows, driver: int, n: int, laps: tuple[Decimal, ...] = STOP_LAPS) -> Rows:
    """A stop on lap n, with its lap before, in-lap, out-lap and lap after."""
    before, in_lap, out_lap, after = laps
    rows.laps.extend([
        lap(driver, n - 1, before),
        lap(driver, n, in_lap),
        lap(driver, n + 1, out_lap, is_pit_out_lap=True),
        lap(driver, n + 2, after),
    ])  # fmt: skip
    rows.pits.append(pit(driver, n))
    return rows


def test_a_stop_costs_its_in_and_out_laps_over_the_laps_around_them() -> None:
    measured = measure_pit_loss(stop(Rows(), 1, 10))

    assert measured == PitLossMeasurement(PitLoss(Decimal("33.000"), 1), ())


def test_the_race_pit_loss_is_the_median_of_its_stops() -> None:
    rows = Rows()
    for driver, out_lap in ((1, 101), (16, 104), (44, 99)):
        stop(rows, driver, 10, (Decimal(90), Decimal(112), Decimal(out_lap), Decimal(90)))

    assert measure_pit_loss(rows).pit_loss == PitLoss(Decimal("33.000"), 3)


def test_an_even_number_of_stops_rounds_their_middle_half_to_even() -> None:
    rows = Rows()
    stop(rows, 1, 10, (Decimal(90), Decimal(112), Decimal("101.001"), Decimal(90)))
    stop(rows, 16, 10, (Decimal(90), Decimal(112), Decimal("101.002"), Decimal(90)))

    assert measure_pit_loss(rows).pit_loss == PitLoss(Decimal("33.002"), 2)


def pit_loss_of(stops: int) -> PitLoss:
    rows = Rows()
    for driver in range(1, stops + 1):
        stop(rows, driver, 10)
    measured = measure_pit_loss(rows).pit_loss
    assert measured is not None
    return measured


def test_a_pit_loss_from_fewer_stops_than_the_minimum_is_not_reliable() -> None:
    assert not pit_loss_of(MIN_RELIABLE_PIT_STOPS - 1).reliable


def test_a_pit_loss_from_the_minimum_of_stops_is_reliable() -> None:
    assert pit_loss_of(MIN_RELIABLE_PIT_STOPS).reliable


def test_a_race_without_stops_has_no_pit_loss() -> None:
    assert measure_pit_loss(Rows()) == PitLossMeasurement(None, ())


def without_lap(rows: Rows, lap_number: int) -> Rows:
    return replace(rows, laps=[one for one in rows.laps if one.lap_number != lap_number])


def with_lap(rows: Rows, lap_number: int, change: Callable[[Lap], Lap]) -> Rows:
    laps = [change(one) if one.lap_number == lap_number else one for one in rows.laps]
    return replace(rows, laps=laps)


def neutralised_on(rows: Rows, lap_number: int) -> Rows:
    window = [
        race_control(1, lap_start(lap_number) + timedelta(seconds=30), "SAFETY CAR DEPLOYED"),
        track_flag(2, lap_start(lap_number + 1) - timedelta(seconds=1), Flag.CLEAR),
    ]
    return replace(rows, race_control=window)


ONE_STOP = stop(Rows(), 1, 10)

EXCLUDED = {
    "lap before is lap 1": (stop(Rows(), 1, 2), PitStopExclusionReason.REFERENCE_IS_FIRST_LAP),
    "lap before missing": (without_lap(ONE_STOP, 9), PitStopExclusionReason.MISSING_LAP),
    "lap after missing": (without_lap(ONE_STOP, 12), PitStopExclusionReason.MISSING_LAP),
    "no duration": (
        with_lap(ONE_STOP, 11, lambda one: replace(one, lap_duration=None)),
        PitStopExclusionReason.UNTIMED_LAP,
    ),
    "no start": (
        with_lap(ONE_STOP, 9, lambda one: replace(one, date_start=None)),
        PitStopExclusionReason.UNTIMED_LAP,
    ),
    "lap before is an out-lap": (
        with_lap(ONE_STOP, 9, lambda one: replace(one, is_pit_out_lap=True)),
        PitStopExclusionReason.NEXT_TO_ANOTHER_STOP,
    ),
    "neutralised in-lap": (neutralised_on(ONE_STOP, 10), PitStopExclusionReason.NEUTRALISED),
    "neutralised lap after": (neutralised_on(ONE_STOP, 12), PitStopExclusionReason.NEUTRALISED),
}


@pytest.mark.parametrize(("rows", "reason"), EXCLUDED.values(), ids=EXCLUDED.keys())
def test_a_stop_that_cannot_be_measured_is_counted_with_its_reason(
    rows: Rows, reason: PitStopExclusionReason
) -> None:
    assert measure_pit_loss(rows) == PitLossMeasurement(None, (PitStopExclusion(reason, 1),))


def race_of_driver_1(pit_laps: tuple[int, ...]) -> Rows:
    """Laps 1 to 20 of driver 1 at 90 s, with a stop on each pit lap."""
    rows = Rows(laps=[lap(1, n, Decimal(90)) for n in range(1, 21)])
    out_laps = {n + 1 for n in pit_laps}
    rows.laps = [replace(one, is_pit_out_lap=one.lap_number in out_laps) for one in rows.laps]
    rows.pits = [pit(1, n) for n in pit_laps]
    return rows


@pytest.mark.parametrize("other_stop_lap", [8, 9, 11, 12])
def test_two_stops_within_two_laps_are_not_measured(other_stop_lap: int) -> None:
    measured = measure_pit_loss(race_of_driver_1((10, other_stop_lap)))

    assert measured == PitLossMeasurement(
        None, (PitStopExclusion(PitStopExclusionReason.NEXT_TO_ANOTHER_STOP, 2),)
    )


def test_a_stop_two_laps_after_another_is_not_measured_when_its_out_lap_is_not_flagged() -> None:
    rows = race_of_driver_1((8, 10))
    rows.laps = [replace(one, is_pit_out_lap=False) for one in rows.laps]

    assert measure_pit_loss(rows) == PitLossMeasurement(
        None, (PitStopExclusion(PitStopExclusionReason.NEXT_TO_ANOTHER_STOP, 2),)
    )


def test_a_stop_on_lap_3_is_measured_against_lap_2() -> None:
    assert measure_pit_loss(stop(Rows(), 1, 3)) == PitLossMeasurement(
        PitLoss(Decimal("33.000"), 1), ()
    )


def test_two_stops_three_laps_apart_are_both_measured() -> None:
    assert measure_pit_loss(race_of_driver_1((10, 13))).pit_loss == PitLoss(Decimal("0.000"), 2)


def test_a_stop_far_from_the_next_is_measured_and_the_exclusions_keep_their_order() -> None:
    rows = stop(stop(Rows(), 1, 10), 1, 20, (Decimal(90), Decimal(110), Decimal(100), Decimal(90)))
    rows = neutralised_on(rows, 21)
    rows.pits.append(pit(44, 2))

    assert measure_pit_loss(rows) == PitLossMeasurement(
        PitLoss(Decimal("33.000"), 1),
        (
            PitStopExclusion(PitStopExclusionReason.REFERENCE_IS_FIRST_LAP, 1),
            PitStopExclusion(PitStopExclusionReason.NEUTRALISED, 1),
        ),
    )


def test_a_lap_with_two_reasons_is_counted_for_the_first() -> None:
    rows = neutralised_on(without_lap(ONE_STOP, 12), 10)

    assert measure_pit_loss(rows).exclusions == (
        PitStopExclusion(PitStopExclusionReason.MISSING_LAP, 1),
    )


def test_rain_does_not_exclude_a_stop() -> None:
    rows = replace(ONE_STOP, weather=[weather(lap_start(n), rainfall=True) for n in range(9, 13)])

    assert measure_pit_loss(rows).pit_loss == PitLoss(Decimal("33.000"), 1)


@given(st.decimals(min_value=-5, max_value=5, places=3), st.data())
def test_a_drivers_pace_and_the_row_order_do_not_move_the_pit_loss(
    shift: Decimal, data: st.DataObject
) -> None:
    rows = stop(stop(Rows(), 1, 10), 16, 30, (Decimal(91), Decimal(115), Decimal(100), Decimal(92)))
    expected = measure_pit_loss(rows)
    shifted = [
        replace(one, lap_duration=one.lap_duration + shift)
        if one.driver_number == 1 and one.lap_duration is not None
        else one
        for one in rows.laps
    ]
    laps = data.draw(st.permutations(shifted))
    pits = data.draw(st.permutations(rows.pits))

    assert measure_pit_loss(replace(rows, laps=laps, pits=pits)) == expected
