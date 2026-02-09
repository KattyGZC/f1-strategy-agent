from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LapBase(BaseModel):
    session_key: int
    driver_number: int
    lap_number: int
    duration_ms: int | None = None
    is_pit_out_lap: bool = False
    stint: int | None = None


class LapCreate(LapBase):
    pass


class LapResponse(LapBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class OpenF1LapResponse(BaseModel):
    """Schema de la respuesta cruda de OpenF1 /laps.

    Nota: OpenF1 devuelve lap_duration en segundos (float).
    La conversión a duration_ms (int) se hace en la capa de ingesta.
    El campo stint no viene de /laps sino de /stints.
    """

    session_key: int | None = None
    meeting_key: int | None = None
    driver_number: int | None = None
    lap_number: int | None = None
    lap_duration: float | None = None
    duration_sector_1: float | None = None
    duration_sector_2: float | None = None
    duration_sector_3: float | None = None
    is_pit_out_lap: bool | None = None
    date_start: datetime | None = None
    i1_speed: int | None = None
    i2_speed: int | None = None
    st_speed: int | None = None
