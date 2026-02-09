from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IntervalBase(BaseModel):
    session_key: int
    driver_number: int
    gap_to_leader: str | None = None
    interval: str | None = None
    date: datetime | None = None


class IntervalCreate(IntervalBase):
    pass


class IntervalResponse(IntervalBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class OpenF1IntervalResponse(BaseModel):
    """Schema de la respuesta cruda de OpenF1 /intervals.

    gap_to_leader e interval pueden ser float (segundos)
    o string ("+1 LAP(S)"). Se almacenan como string.
    """

    session_key: int | None = None
    meeting_key: int | None = None
    driver_number: int | None = None
    gap_to_leader: float | str | None = None
    interval: float | str | None = None
    date: datetime | None = None
