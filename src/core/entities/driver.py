from pydantic import BaseModel, ConfigDict


class DriverBase(BaseModel):
    driver_number: int
    full_name: str
    team_name: str
    country_code: str | None = None


class DriverCreate(DriverBase):
    pass


class DriverResponse(DriverBase):
    model_config = ConfigDict(from_attributes=True)


class OpenF1DriverResponse(BaseModel):
    """Schema de la respuesta cruda de OpenF1 /drivers."""

    driver_number: int
    full_name: str
    team_name: str | None = None
    country_code: str | None = None
    broadcast_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    name_acronym: str | None = None
    headshot_url: str | None = None
    team_colour: str | None = None
    session_key: int | None = None
    meeting_key: int | None = None
