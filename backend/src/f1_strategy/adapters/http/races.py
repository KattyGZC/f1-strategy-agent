"""Race routes: the calibrated races, and what each one's model carries for the simulator's
form (ADR 0017)."""

from fastapi import APIRouter
from pydantic import AwareDatetime, BaseModel, Field

from f1_strategy.adapters.http.responses import INVALID, NOT_FOUND
from f1_strategy.adapters.http.services import Services
from f1_strategy.adapters.http.sessions import SessionKey
from f1_strategy.application.simulation import CalibratedRace
from f1_strategy.domain.clean import Compound
from f1_strategy.domain.lap_time_model import CompoundFit
from f1_strategy.domain.pit_loss import PitLoss
from f1_strategy.domain.strategy import NotModelled

router = APIRouter(tags=["races"])


class RaceResponse(BaseModel):
    session_key: int
    date_start: AwareDatetime
    year: int
    meeting_name: str
    circuit_short_name: str
    country_name: str
    race_laps: int


class CompoundResponse(BaseModel):
    compound: Compound
    min_tyre_age_laps: int = Field(description="The youngest tyre among its clean laps")
    max_tyre_age_laps: int = Field(description="The oldest tyre among its clean laps")
    residual_rmse_s: float = Field(description="The model's error on its clean laps")


class PitLossResponse(BaseModel):
    pit_loss_s: float
    stops: int = Field(description="The stops it was measured on")
    reliable: bool = Field(description="False when measured on fewer than 5 stops")


class TrackTemperatureResponse(BaseModel):
    min_c: float
    median_c: float
    max_c: float


class RaceModelResponse(BaseModel):
    session_key: int
    race_laps: int
    compounds: list[CompoundResponse] = Field(description="The compounds a stint can run")
    driver_numbers: list[int] = Field(description="The drivers with a calibrated pace, by number")
    residual_rmse_s: float = Field(description="The model's error on the race's clean laps")
    pit_loss: PitLossResponse | None = Field(description="None when no stop could be measured")
    track_temperature: TrackTemperatureResponse | None
    rain_readings: int
    not_modelled: list[NotModelled]


@router.get("/races")
async def list_races(services: Services) -> list[RaceResponse]:
    """Every calibrated race, the earliest first."""
    return [_race(race) for race in await services.list_races()]


@router.get("/races/{session_key}", responses={**NOT_FOUND, **INVALID})
async def read_race(session_key: SessionKey, services: Services) -> RaceModelResponse:
    race = await services.read_race(session_key)
    calibration = race.calibration
    temperature = calibration.track_temperature
    return RaceModelResponse(
        session_key=session_key,
        race_laps=calibration.race_laps,
        compounds=[_compound(fit) for fit in calibration.compounds],
        driver_numbers=[pace.driver_number for pace in calibration.drivers],
        residual_rmse_s=float(calibration.residual_rmse_s),
        pit_loss=None if calibration.pit_loss is None else _pit_loss(calibration.pit_loss),
        track_temperature=(
            None
            if temperature is None
            else TrackTemperatureResponse.model_validate(temperature, from_attributes=True)
        ),
        rain_readings=calibration.rain_readings,
        not_modelled=list(race.not_modelled),
    )


def _race(race: CalibratedRace) -> RaceResponse:
    return RaceResponse.model_validate(race, from_attributes=True)


def _compound(fit: CompoundFit) -> CompoundResponse:
    return CompoundResponse.model_validate(fit, from_attributes=True)


def _pit_loss(pit_loss: PitLoss) -> PitLossResponse:
    return PitLossResponse.model_validate(pit_loss, from_attributes=True)
