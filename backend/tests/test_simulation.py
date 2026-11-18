from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from f1_strategy.application.simulation import (
    CalibratedRace,
    ListRaces,
    RaceModel,
    RaceNotCalibratedError,
    ReadRace,
    SimulateStrategies,
    Simulation,
)
from f1_strategy.domain.lap_time_model import Calibration
from f1_strategy.domain.strategy import DriverNotCalibratedError, NotModelled, simulate
from tests.simulated_race import CALIBRATION, DRIVER, HARD_ONLY, SOFT_THEN_HARD

RACE_KEY, OTHER_KEY = 9472, 9480
RACE = CalibratedRace(
    session_key=RACE_KEY,
    date_start=datetime(2024, 3, 2, 15, tzinfo=UTC),
    year=2024,
    meeting_name="Bahrain Grand Prix",
    circuit_short_name="Sakhir",
    country_name="Bahrain",
    race_laps=CALIBRATION.race_laps,
)
DRY_RACE_NOT_MODELLED = (
    NotModelled.STANDING_START,
    NotModelled.STARTING_FUEL,
    NotModelled.WIND,
    NotModelled.DRIVER_AGGRESSIVENESS,
    NotModelled.TRACK_TEMPERATURE,
)


@dataclass
class FakeRaces:
    """The stored calibrations by race."""

    calibrations: dict[int, Calibration]

    async def races(self) -> tuple[CalibratedRace, ...]:
        return (RACE,) if RACE_KEY in self.calibrations else ()

    async def calibration(self, session_key: int) -> Calibration | None:
        return self.calibrations.get(session_key)


@pytest.mark.anyio
async def test_the_races_are_the_stored_list() -> None:
    assert await ListRaces(FakeRaces({RACE_KEY: CALIBRATION}))() == (RACE,)
    assert await ListRaces(FakeRaces({}))() == ()


@pytest.mark.parametrize(
    ("rain_readings", "expected"),
    [
        pytest.param(0, DRY_RACE_NOT_MODELLED, id="dry"),
        pytest.param(3, (*DRY_RACE_NOT_MODELLED, NotModelled.RAIN_ON_SLICKS), id="rain"),
    ],
)
@pytest.mark.anyio
async def test_a_race_is_its_calibration_and_what_it_leaves_out(
    rain_readings: int, expected: tuple[NotModelled, ...]
) -> None:
    calibration = replace(CALIBRATION, rain_readings=rain_readings)

    race = await ReadRace(FakeRaces({RACE_KEY: calibration}))(RACE_KEY)

    assert race == RaceModel(calibration, expected)


@pytest.mark.anyio
async def test_strategies_are_simulated_on_the_stored_calibration() -> None:
    simulate_strategies = SimulateStrategies(FakeRaces({RACE_KEY: CALIBRATION}))

    simulation = await simulate_strategies(RACE_KEY, DRIVER, [SOFT_THEN_HARD, HARD_ONLY])

    assert simulation == Simulation(
        simulate(CALIBRATION, [SOFT_THEN_HARD, HARD_ONLY], DRIVER), DRY_RACE_NOT_MODELLED
    )


@pytest.mark.anyio
async def test_a_race_without_a_calibration_is_refused_whole() -> None:
    races = FakeRaces({OTHER_KEY: CALIBRATION})

    with pytest.raises(RaceNotCalibratedError, match="race 9472 has no calibration"):
        await ReadRace(races)(RACE_KEY)
    with pytest.raises(RaceNotCalibratedError, match="race 9472 has no calibration"):
        await SimulateStrategies(races)(RACE_KEY, None, [HARD_ONLY])


@pytest.mark.anyio
async def test_a_driver_without_a_calibrated_pace_is_refused_whole() -> None:
    simulate_strategies = SimulateStrategies(FakeRaces({RACE_KEY: CALIBRATION}))

    with pytest.raises(DriverNotCalibratedError, match="driver 99 has no calibrated pace"):
        await simulate_strategies(RACE_KEY, 99, [HARD_ONLY])
