"""Session routes: which sessions of the clean model can be replayed, and who drove in each."""

from typing import Annotated

from fastapi import APIRouter, Path
from pydantic import AwareDatetime, BaseModel, Field

from f1_strategy.adapters.http.responses import NOT_FOUND
from f1_strategy.adapters.http.services import Services
from f1_strategy.application.sessions import LoadedSession, SessionDriver
from f1_strategy.domain.openf1 import SessionName, SessionType

router = APIRouter(tags=["sessions"])

SessionKey = Annotated[int, Path(gt=0)]


class SessionResponse(BaseModel):
    session_key: int
    session_type: SessionType
    session_name: SessionName
    date_start: AwareDatetime
    year: int
    meeting_name: str
    circuit_short_name: str
    country_name: str


class DriverResponse(BaseModel):
    driver_number: int
    name_acronym: str
    full_name: str
    team_name: str
    team_colour: str = Field(description="RGB in hex, without the leading #")


class SessionEntryResponse(SessionResponse):
    drivers: list[DriverResponse] = Field(description="By driver number")


@router.get("/sessions")
async def list_sessions(services: Services) -> list[SessionResponse]:
    """Every session loaded in the clean model, the latest first."""
    return [_session(session) for session in await services.list_sessions()]


@router.get("/sessions/{session_key}", responses=NOT_FOUND)
async def read_session(session_key: SessionKey, services: Services) -> SessionEntryResponse:
    entry = await services.read_session(session_key)
    return SessionEntryResponse(
        **_session(entry.session).model_dump(),
        drivers=[_driver(driver) for driver in entry.drivers],
    )


def _session(session: LoadedSession) -> SessionResponse:
    return SessionResponse.model_validate(session, from_attributes=True)


def _driver(driver: SessionDriver) -> DriverResponse:
    return DriverResponse.model_validate(driver, from_attributes=True)
