from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from statistics import median

import pytest

from f1_strategy.domain.clean import Compound, Flag, FlagScope, Lap, RaceControlCategory
from f1_strategy.domain.clean_laps import (
    DRYING_MARGIN,
    MIN_COMPOUND_CLEAN_LAPS,
    MIN_DRIVER_CLEAN_LAPS,
    OUTLIER_FACTOR,
    CalibrationDataError,
    CleanLap,
    ExcludedLap,
    ExclusionReason,
    LapVerdict,
    Window,
    lap_verdicts,
    neutralisation_windows,
    rain_windows,
)
from f1_strategy.domain.tyres import Tyre
from tests.replay_rows import Rows
from tests.synthetic_race import (
    LAP_START_EVERY_S,
    T0,
    PlannedStint,
    flag_row,
    lap,
    lap_start,
    pit,
    race_control,
    stint,
    synthetic_race,
    track_flag,
    weather,
)


def verdict(rows: Rows, driver: int, lap_number: int) -> LapVerdict:
    return next(
        one
        for one in lap_verdicts(rows)
        if one.lap.driver_number == driver and one.lap.lap_number == lap_number
    )


def reason(rows: Rows, driver: int, lap_number: int) -> ExclusionReason | None:
    one = verdict(rows, driver, lap_number)
    return one.reason if isinstance(one, ExcludedLap) else None


def with_lap(rows: Rows, driver: int, lap_number: int, change: Callable[[Lap], Lap]) -> Rows:
    rows.laps = [
        change(one) if (one.driver_number, one.lap_number) == (driver, lap_number) else one
        for one in rows.laps
    ]
    return rows


def test_a_racing_lap_is_clean_with_its_tyre() -> None:
    clean = verdict(synthetic_race(), 1, 5)

    assert clean == CleanLap(clean.lap, Decimal("90.66"), Tyre(Compound.SOFT, 4))


def test_every_lap_but_the_first_of_a_clean_race_is_clean() -> None:
    verdicts = lap_verdicts(synthetic_race())

    excluded = [(one.lap.driver_number, one.lap.lap_number, one.reason)
                for one in verdicts if isinstance(one, ExcludedLap)]  # fmt: skip
    assert excluded == [(1, 1, ExclusionReason.FIRST_LAP), (44, 1, ExclusionReason.FIRST_LAP)]
    assert len(verdicts) == 120


def test_verdicts_are_in_driver_and_lap_order_whatever_the_input_order() -> None:
    rows = synthetic_race()
    rows.laps.reverse()

    keys = [(one.lap.driver_number, one.lap.lap_number) for one in lap_verdicts(rows)]

    assert keys == sorted(keys)


def test_a_lap_without_a_duration_is_excluded() -> None:
    rows = with_lap(synthetic_race(), 1, 5, lambda one: replace(one, lap_duration=None))

    assert reason(rows, 1, 5) == ExclusionReason.NO_DURATION


def test_a_lap_no_stint_covers_is_excluded() -> None:
    rows = synthetic_race()
    rows.laps.append(lap(1, 61))

    assert reason(rows, 1, 61) == ExclusionReason.NO_STINT


@pytest.mark.parametrize("compound", [Compound.WET, Compound.UNKNOWN])
def test_a_lap_on_a_compound_the_model_does_not_calibrate_is_excluded(compound: Compound) -> None:
    rows = synthetic_race()
    rows.stints.append(stint(1, 3, PlannedStint(compound, 61, 61)))
    rows.laps.append(lap(1, 61))

    assert reason(rows, 1, 61) == ExclusionReason.NOT_CALIBRATED_COMPOUND


def test_the_first_lap_is_excluded_before_it_counts_as_a_pit_out_lap() -> None:
    rows = with_lap(synthetic_race(), 1, 1, lambda one: replace(one, is_pit_out_lap=True))

    assert reason(rows, 1, 1) == ExclusionReason.FIRST_LAP


def test_a_pit_out_lap_is_excluded() -> None:
    rows = with_lap(synthetic_race(), 1, 31, lambda one: replace(one, is_pit_out_lap=True))

    assert reason(rows, 1, 31) == ExclusionReason.PIT_OUT_LAP


def test_the_lap_a_driver_pits_on_is_excluded_and_not_the_next_drivers() -> None:
    rows = synthetic_race()
    rows.pits.append(pit(1, 20))

    assert (reason(rows, 1, 20), reason(rows, 44, 20)) == (ExclusionReason.PIT_IN_LAP, None)


def test_a_lap_without_a_start_is_excluded() -> None:
    rows = synthetic_race()
    rows.laps = [
        replace(one, date_start=None) if (one.driver_number, one.lap_number) == (1, 5) else one
        for one in rows.laps
    ]

    assert reason(rows, 1, 5) == ExclusionReason.NO_START_INSTANT


def neutralised_race(*, laps: tuple[int, int] = (10, 12)) -> Rows:
    """A safety car from inside lap `laps[0]` to inside lap `laps[1]`."""
    rows = synthetic_race()
    rows.race_control = [
        race_control(1, lap_start(laps[0]) + timedelta(seconds=30), "SAFETY CAR DEPLOYED"),
        track_flag(2, lap_start(laps[1]) + timedelta(seconds=30), Flag.CLEAR),
    ]
    return rows


def test_laps_a_neutralisation_overlaps_are_excluded_and_the_next_one_is_a_restart() -> None:
    rows = neutralised_race()

    reasons = [reason(rows, 1, lap_number) for lap_number in range(9, 15)]

    assert reasons == [
        None,
        ExclusionReason.NEUTRALISED,
        ExclusionReason.NEUTRALISED,
        ExclusionReason.NEUTRALISED,
        ExclusionReason.RESTART_LAP,
        None,
    ]


def test_a_lap_that_ends_as_a_window_opens_is_not_neutralised() -> None:
    rows = synthetic_race()
    lap_9 = next(one for one in rows.laps if (one.driver_number, one.lap_number) == (1, 9))
    assert lap_9.date_start is not None
    assert lap_9.lap_duration is not None
    lap_9_end = lap_9.date_start + timedelta(seconds=float(lap_9.lap_duration))
    rows.race_control = [
        race_control(1, lap_9_end, "SAFETY CAR DEPLOYED"),
        track_flag(2, lap_start(12), Flag.CLEAR),
    ]

    assert (reason(rows, 1, 9), reason(rows, 1, 10)) == (None, ExclusionReason.NEUTRALISED)


def test_a_lap_that_starts_as_a_window_closes_is_only_a_restart() -> None:
    rows = synthetic_race()
    rows.race_control = [
        race_control(1, lap_start(10), "SAFETY CAR DEPLOYED"),
        track_flag(2, lap_start(11), Flag.CLEAR),
    ]

    assert (reason(rows, 1, 10), reason(rows, 1, 11)) == (
        ExclusionReason.NEUTRALISED,
        ExclusionReason.RESTART_LAP,
    )


def rainy_race(compound: Compound) -> Rows:
    """Driver 1 on `compound` for laps 2 to 20, with one rainy reading in lap 5."""
    rows = synthetic_race()
    rows.stints = [
        replace(one, compound=compound) if (one.driver_number, one.stint_number) == (1, 1) else one
        for one in rows.stints
    ]
    rows.weather = [weather(lap_start(5), rainfall=True), weather(lap_start(6))]
    return rows


def test_a_dry_lap_in_the_rain_or_the_drying_margin_after_it_is_excluded() -> None:
    rows = rainy_race(Compound.SOFT)
    margin_laps = DRYING_MARGIN // timedelta(seconds=LAP_START_EVERY_S)

    reasons = [reason(rows, 1, n) for n in (4, 5, 4 + margin_laps, 5 + margin_laps)]

    assert reasons == [None, ExclusionReason.WET_TRACK, ExclusionReason.WET_TRACK, None]


def test_an_intermediate_lap_in_the_rain_is_clean() -> None:
    rows = rainy_race(Compound.INTERMEDIATE)
    rows.stints.append(stint(44, 3, PlannedStint(Compound.INTERMEDIATE, 61, 80)))
    rows.laps.extend(lap(44, n) for n in range(61, 81))

    assert reason(rows, 1, 5) is None


def test_a_lap_slower_than_the_outlier_limit_of_its_compound_is_excluded() -> None:
    rows = synthetic_race()
    soft_median_s = median(
        one.lap_duration
        for one in lap_verdicts(rows)
        if isinstance(one, CleanLap) and one.tyre.compound == Compound.SOFT
    )
    limit_s = soft_median_s * OUTLIER_FACTOR
    # Laps 29 and 30 of driver 1 are the slowest soft laps, so moving them keeps the median.
    rows = with_lap(rows, 1, 29, lambda one: replace(one, lap_duration=limit_s))
    rows = with_lap(rows, 1, 30, lambda one: replace(one, lap_duration=limit_s + Decimal("0.001")))

    assert (reason(rows, 1, 29), reason(rows, 1, 30)) == (None, ExclusionReason.OUTLIER)


def test_a_compound_with_too_few_clean_laps_is_excluded_whole() -> None:
    rows = synthetic_race()
    rows.stints.append(
        stint(1, 3, PlannedStint(Compound.MEDIUM, 61, 61 + MIN_COMPOUND_CLEAN_LAPS - 2))
    )
    rows.laps.extend(lap(1, n) for n in range(61, 61 + MIN_COMPOUND_CLEAN_LAPS - 1))

    assert reason(rows, 1, 61) == ExclusionReason.COMPOUND_TOO_FEW_LAPS


def test_a_compound_with_enough_clean_laps_stays() -> None:
    rows = synthetic_race()
    rows.stints.append(
        stint(1, 3, PlannedStint(Compound.MEDIUM, 61, 61 + MIN_COMPOUND_CLEAN_LAPS - 1))
    )
    rows.laps.extend(lap(1, n) for n in range(61, 61 + MIN_COMPOUND_CLEAN_LAPS))

    assert reason(rows, 1, 61) is None


@pytest.mark.parametrize(("laps", "expected"), [
    (MIN_DRIVER_CLEAN_LAPS - 1, ExclusionReason.DRIVER_TOO_FEW_LAPS),
    (MIN_DRIVER_CLEAN_LAPS, None),
])  # fmt: skip
def test_a_driver_with_too_few_clean_laps_is_excluded(
    laps: int, expected: ExclusionReason | None
) -> None:
    rows = synthetic_race()
    rows.stints.append(stint(16, 1, PlannedStint(Compound.HARD, 2, 1 + laps)))
    rows.laps.extend(lap(16, n, Decimal(91)) for n in range(2, 2 + laps))

    assert reason(rows, 16, 2) == expected


def test_a_safety_car_window_runs_to_the_next_track_clear() -> None:
    rows = [
        race_control(1, T0, "SAFETY CAR DEPLOYED"),
        race_control(2, T0 + timedelta(minutes=3), "SAFETY CAR IN THIS LAP"),
        track_flag(3, T0 + timedelta(minutes=4), Flag.CLEAR),
    ]

    assert neutralisation_windows(rows) == (Window(T0, T0 + timedelta(minutes=4)),)


def test_a_virtual_safety_car_ends_on_green_and_a_red_flag_on_clear() -> None:
    rows = [
        race_control(1, T0, "VIRTUAL SAFETY CAR DEPLOYED"),
        race_control(2, T0 + timedelta(minutes=1), "VIRTUAL SAFETY CAR ENDING"),
        track_flag(3, T0 + timedelta(minutes=2), Flag.GREEN),
        track_flag(4, T0 + timedelta(minutes=5), Flag.RED),
        track_flag(5, T0 + timedelta(minutes=30), Flag.CLEAR),
    ]

    assert neutralisation_windows(rows) == (
        Window(T0, T0 + timedelta(minutes=2)),
        Window(T0 + timedelta(minutes=5), T0 + timedelta(minutes=30)),
    )


def test_a_deployment_inside_an_open_window_does_not_reopen_it() -> None:
    rows = [
        race_control(1, T0, "VIRTUAL SAFETY CAR DEPLOYED"),
        race_control(2, T0 + timedelta(minutes=1), "SAFETY CAR DEPLOYED"),
        race_control(3, T0 + timedelta(minutes=2), "SAFETY CAR THROUGH THE PIT LANE"),
        track_flag(4, T0 + timedelta(minutes=4), Flag.CLEAR),
    ]

    assert neutralisation_windows(rows) == (Window(T0, T0 + timedelta(minutes=4)),)


def test_a_sector_clear_or_a_clear_with_no_window_open_changes_nothing() -> None:
    sector_clear = flag_row(2, T0 + timedelta(minutes=1), Flag.CLEAR, FlagScope.SECTOR)
    rows = [
        track_flag(1, T0, Flag.GREEN),
        race_control(3, T0 + timedelta(minutes=2), "SAFETY CAR DEPLOYED"),
        sector_clear,
    ]

    assert neutralisation_windows(rows) == (Window(T0 + timedelta(minutes=2), None),)


def test_a_window_still_open_lasts_to_the_end_of_the_race() -> None:
    rows = synthetic_race()
    rows.race_control = [race_control(1, lap_start(59), "SAFETY CAR DEPLOYED")]

    assert (reason(rows, 1, 58), reason(rows, 1, 60)) == (None, ExclusionReason.NEUTRALISED)


def test_rows_of_one_instant_are_read_in_sequence_order() -> None:
    rows = [
        track_flag(2, T0, Flag.CLEAR),
        race_control(1, T0, "SAFETY CAR DEPLOYED"),
    ]

    assert neutralisation_windows(rows) == (Window(T0, T0),)


def test_a_safety_car_message_outside_the_known_set_fails_loudly() -> None:
    rows = [race_control(7, T0, "SAFETY CAR STAYING OUT")]

    with pytest.raises(CalibrationDataError, match="race_control seq 7: safety car message"):
        neutralisation_windows(rows)


def test_a_safety_car_message_outside_the_known_set_fails_inside_a_window_too() -> None:
    rows = [
        race_control(1, T0, "SAFETY CAR DEPLOYED"),
        race_control(2, T0 + timedelta(minutes=1), "SAFETY CAR STAYING OUT"),
    ]

    with pytest.raises(CalibrationDataError, match="race_control seq 2: safety car message"):
        neutralisation_windows(rows)


def test_a_notice_with_no_window_open_opens_none() -> None:
    rows = [race_control(1, T0, "SAFETY CAR IN THIS LAP")]

    assert neutralisation_windows(rows) == ()


def test_other_categories_never_open_a_window() -> None:
    rows = [race_control(1, T0, "DRS ENABLED", RaceControlCategory.DRS)]

    assert neutralisation_windows(rows) == ()


def test_each_run_of_rain_lasts_to_the_drying_margin_after_its_last_reading() -> None:
    readings = [
        weather(T0 + timedelta(minutes=3), rainfall=True),
        weather(T0, rainfall=True),
        weather(T0 + timedelta(minutes=1), rainfall=True),
        weather(T0 + timedelta(minutes=4)),
        weather(T0 + timedelta(minutes=2)),
        weather(T0 + timedelta(minutes=9), rainfall=True),
    ]

    assert rain_windows(readings) == (
        Window(T0, T0 + timedelta(minutes=1) + DRYING_MARGIN),
        Window(T0 + timedelta(minutes=3), T0 + timedelta(minutes=3) + DRYING_MARGIN),
        Window(T0 + timedelta(minutes=9), T0 + timedelta(minutes=9) + DRYING_MARGIN),
    )


def test_a_dry_race_has_no_rain_window() -> None:
    assert rain_windows([weather(T0), weather(T0 + timedelta(minutes=1))]) == ()
