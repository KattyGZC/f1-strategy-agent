"""The calibrated races a viewer can simulate strategies on (ADR 0017)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from f1_strategy.domain.lap_time_model import Calibration


@dataclass(frozen=True)
class CalibratedRace:
    session_key: int
    date_start: datetime
    year: int
    meeting_name: str
    circuit_short_name: str
    country_name: str
    race_laps: int


class CalibratedRaces(Protocol):
    async def races(self) -> tuple[CalibratedRace, ...]:
        """Every calibrated race, the earliest first."""
        ...

    async def calibration(self, session_key: int) -> Calibration | None:
        """The race's stored calibration, or None if the race is not calibrated."""
        ...
