"""The simulation route: race strategies compared on one race's calibration (ADR 0017)."""

from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from f1_strategy.adapters.http.responses import INVALID, NOT_FOUND
from f1_strategy.adapters.http.services import Services
from f1_strategy.domain.clean import Compound
from f1_strategy.domain.strategy import (
    Caveat,
    NotModelled,
    Rejected,
    StrategyRejection,
    StrategyResult,
    StrategyStint,
)

# The schema bounds of a simulation (ADR 0017).
MAX_STRATEGIES = 4
MAX_STINTS = 6
MAX_TYRE_AGE_LAPS = 99

router = APIRouter(tags=["simulations"])


class StintRequest(BaseModel):
    compound: Compound
    laps: int = Field(ge=1)
    tyre_age_at_start_laps: int = Field(ge=0, le=MAX_TYRE_AGE_LAPS, description="0 is a new set")


Stints = Annotated[list[StintRequest], Field(min_length=1, max_length=MAX_STINTS)]


class SimulationRequest(BaseModel):
    session_key: int = Field(gt=0)
    driver_number: int | None = Field(
        default=None, gt=0, description="None simulates the average car of the race"
    )
    strategies: list[Stints] = Field(
        min_length=1,
        max_length=MAX_STRATEGIES,
        description="Each strategy's stints in order; the first starts on lap 1",
    )


class LapResponse(BaseModel):
    lap_number: int
    tyre_age_laps: int
    lap_time_s: float
    extrapolated: bool = Field(description="The tyre is older or newer than any calibrated lap")


class StintResponse(BaseModel):
    compound: Compound
    laps: list[LapResponse]


class StopResponse(BaseModel):
    in_lap: int
    pit_loss_s: float


class SimulatedResponse(BaseModel):
    outcome: Literal["simulated"] = "simulated"
    stints: list[StintResponse]
    stops: list[StopResponse]
    total_s: float = Field(description="The laps and the stops; not a race result")
    gap_to_fastest_s: float = Field(description="Against the fastest simulated strategy")
    caveats: list[Caveat]


class RejectedResponse(BaseModel):
    outcome: Literal["rejected"] = "rejected"
    reason: StrategyRejection
    stint_number: int | None = Field(description="None when the reason is the whole strategy's")


type StrategyResponse = Annotated[
    SimulatedResponse | RejectedResponse, Field(discriminator="outcome")
]


class SimulationResponse(BaseModel):
    results: list[StrategyResponse] = Field(description="In the order of the strategies")
    not_modelled: list[NotModelled] = Field(description="What every strategy of the race omits")


@router.post("/simulations", responses={**NOT_FOUND, **INVALID})
async def simulate_strategies(body: SimulationRequest, services: Services) -> SimulationResponse:
    """Nothing is stored: the strategies are simulated on the race's calibration on every
    request."""
    simulation = await services.simulate(
        body.session_key,
        body.driver_number,
        [[_stint(stint) for stint in stints] for stints in body.strategies],
    )
    return SimulationResponse(
        results=[_result(result) for result in simulation.results],
        not_modelled=list(simulation.not_modelled),
    )


def _stint(stint: StintRequest) -> StrategyStint:
    return StrategyStint(stint.compound, stint.laps, stint.tyre_age_at_start_laps)


def _result(result: StrategyResult) -> SimulatedResponse | RejectedResponse:
    if isinstance(result, Rejected):
        return RejectedResponse.model_validate(result, from_attributes=True)
    return SimulatedResponse.model_validate(result, from_attributes=True)
