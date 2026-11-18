"""The calibrated races a viewer can simulate strategies on, and the simulation (ADR 0017)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from f1_strategy.domain.lap_time_model import Calibration
from f1_strategy.domain.strategy import (
    NotModelled,
    StrategyResult,
    StrategyStint,
    not_modelled,
    simulate,
)


class RaceNotCalibratedError(LookupError):
    def __init__(self, session_key: int) -> None:
        super().__init__(f"race {session_key} has no calibration; run the calibration first")
        self.session_key = session_key


@dataclass(frozen=True)
class CalibratedRace:
    session_key: int
    date_start: datetime
    year: int
    meeting_name: str
    circuit_short_name: str
    country_name: str
    race_laps: int


@dataclass(frozen=True)
class RaceModel:
    calibration: Calibration
    not_modelled: tuple[NotModelled, ...]


@dataclass(frozen=True)
class Simulation:
    results: tuple[StrategyResult, ...]
    not_modelled: tuple[NotModelled, ...]


class CalibratedRaces(Protocol):
    async def races(self) -> tuple[CalibratedRace, ...]:
        """Every calibrated race, the earliest first."""
        ...

    async def calibration(self, session_key: int) -> Calibration | None:
        """The race's stored calibration, or None if the race is not calibrated."""
        ...


class ListRaces:
    def __init__(self, races: CalibratedRaces) -> None:
        self._races = races

    async def __call__(self) -> tuple[CalibratedRace, ...]:
        return await self._races.races()


class ReadRace:
    def __init__(self, races: CalibratedRaces) -> None:
        self._races = races

    async def __call__(self, session_key: int) -> RaceModel:
        calibration = await _calibration(self._races, session_key)
        return RaceModel(calibration, not_modelled(calibration))


class SimulateStrategies:
    def __init__(self, races: CalibratedRaces) -> None:
        self._races = races

    async def __call__(
        self,
        session_key: int,
        driver_number: int | None,
        strategies: Sequence[Sequence[StrategyStint]],
    ) -> Simulation:
        """Recomputed from the stored calibration on every call: nothing is stored."""
        calibration = await _calibration(self._races, session_key)
        results = simulate(calibration, strategies, driver_number)
        return Simulation(results, not_modelled(calibration))


async def _calibration(races: CalibratedRaces, session_key: int) -> Calibration:
    calibration = await races.calibration(session_key)
    if calibration is None:
        raise RaceNotCalibratedError(session_key)
    return calibration
