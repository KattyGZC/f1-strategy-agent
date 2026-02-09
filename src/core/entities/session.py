from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionBase(BaseModel):
    session_key: int
    session_name: str
    circuit_short_name: str
    date_start: datetime | None = None
    year: int


class SessionCreate(SessionBase):
    pass


class SessionResponse(SessionBase):
    model_config = ConfigDict(from_attributes=True)


class OpenF1SessionResponse(BaseModel):
    """Schema de la respuesta cruda de OpenF1 /sessions."""

    session_key: int
    session_name: str
    session_type: str | None = None
    circuit_key: int | None = None
    circuit_short_name: str | None = None
    date_start: datetime | None = None
    date_end: datetime | None = None
    year: int | None = None
    meeting_key: int | None = None
    country_name: str | None = None
    country_code: str | None = None
    location: str | None = None
    gmt_offset: str | None = None
