from pydantic import BaseModel, ConfigDict


class RaceSummaryBase(BaseModel):
    session_key: int
    content: str


class RaceSummaryCreate(RaceSummaryBase):
    embedding: list[float] | None = None


class RaceSummaryResponse(RaceSummaryBase):
    id: int
    model_config = ConfigDict(from_attributes=True)
