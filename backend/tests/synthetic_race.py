"""Races built from known coefficients, so a calibration has an exact answer to recover."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
from tests.replay_rows import Rows

SESSION = 9472
T0 = datetime(2024, 3, 2, 15, tzinfo=UTC)
LAP_START_EVERY_S = 100


@dataclass(frozen=True)
class PlannedStint:
    compound: Compound
    lap_start: int
    lap_end: int
    tyre_age_at_start: int = 0


@dataclass(frozen=True)
class Truth:
    """The coefficients a synthetic race's lap times are computed from."""

    base_s: dict[Compound, Decimal]
    degradation_s_per_lap: dict[Compound, Decimal]
    progress_s_per_lap: dict[Compound, Decimal]
    pace_offset_s: dict[int, Decimal]

    def lap_time_s(self, driver: int, stint: PlannedStint, lap_number: int) -> Decimal:
        age = stint.tyre_age_at_start + lap_number - stint.lap_start
        return (
            self.base_s[stint.compound]
            + self.pace_offset_s[driver]
            + self.degradation_s_per_lap[stint.compound] * age
            + self.progress_s_per_lap[stint.compound] * (lap_number - 1)
        )


DRY = Truth(
    base_s={Compound.SOFT: Decimal("90.2"), Compound.HARD: Decimal(91)},
    degradation_s_per_lap={Compound.SOFT: Decimal("0.1"), Compound.HARD: Decimal("0.04")},
    progress_s_per_lap={Compound.SOFT: Decimal("-0.06"), Compound.HARD: Decimal("-0.06")},
    pace_offset_s={1: Decimal("0.3"), 44: Decimal("-0.3")},
)
DRY_PLAN = {
    1: (PlannedStint(Compound.SOFT, 1, 30), PlannedStint(Compound.HARD, 31, 60)),
    44: (PlannedStint(Compound.HARD, 1, 30), PlannedStint(Compound.SOFT, 31, 60)),
}


def lap_start(lap_number: int) -> datetime:
    return T0 + timedelta(seconds=LAP_START_EVERY_S * (lap_number - 1))


def lap(
    driver: int,
    lap_number: int,
    duration_s: Decimal | None = Decimal(90),
    *,
    date_start: datetime | None = None,
    is_pit_out_lap: bool = False,
) -> Lap:
    start = lap_start(lap_number) if date_start is None else date_start
    return Lap(
        SESSION, driver, lap_number, start, duration_s,
        None, None, None, None, None, None, is_pit_out_lap=is_pit_out_lap,
    )  # fmt: skip


def stint(driver: int, number: int, planned: PlannedStint) -> Stint:
    return Stint(
        SESSION, driver, number, planned.compound, planned.lap_start, planned.lap_end,
        planned.tyre_age_at_start,
    )  # fmt: skip


def pit(driver: int, lap_number: int) -> Pit:
    return Pit(SESSION, driver, lap_number, lap_start(lap_number + 1), Decimal(22), None)


def race_control(
    seq: int,
    at: datetime,
    message: str,
    category: RaceControlCategory = RaceControlCategory.SAFETY_CAR,
) -> RaceControl:
    return RaceControl(SESSION, seq, at, category, None, None, None, None, None, None, message)


def flag_row(seq: int, at: datetime, flag: Flag, scope: FlagScope) -> RaceControl:
    category = RaceControlCategory.FLAG
    return RaceControl(SESSION, seq, at, category, flag, scope, None, None, None, None, flag.value)


def track_flag(seq: int, at: datetime, flag: Flag) -> RaceControl:
    return flag_row(seq, at, flag, FlagScope.TRACK)


def weather(at: datetime, *, rainfall: bool = False, track_c: Decimal = Decimal(30)) -> Weather:
    return Weather(
        SESSION, at, Decimal(25), track_c, Decimal(50), Decimal(1013), rainfall=rainfall,
        wind_speed=Decimal(1), wind_direction=90,
    )  # fmt: skip


def synthetic_race(
    truth: Truth = DRY, plan: Mapping[int, Sequence[PlannedStint]] | None = None
) -> Rows:
    """Every lap of every planned stint at the time the truth gives, a lap starting every 100 s."""
    rows = Rows()
    for driver, stints in (DRY_PLAN if plan is None else plan).items():
        for number, planned in enumerate(stints, 1):
            rows.stints.append(stint(driver, number, planned))
            for lap_number in range(planned.lap_start, planned.lap_end + 1):
                lap_time_s = truth.lap_time_s(driver, planned, lap_number)
                rows.laps.append(lap(driver, lap_number, lap_time_s))
    rows.weather.append(weather(lap_start(10)))
    return rows
