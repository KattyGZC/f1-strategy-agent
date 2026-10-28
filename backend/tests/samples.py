import json
from dataclasses import dataclass
from pathlib import Path

from f1_strategy.domain.clean import RawSession
from f1_strategy.domain.openf1 import Endpoint, JsonObject

SAMPLE = Path(__file__).parent / "fixtures" / "openf1_2024_bahrain_sample.json"
RACE = "9472"
QUALIFYING = "9468"


@dataclass
class Sample:
    """A mutable copy of one sampled session, to break before cleaning it."""

    session: JsonObject
    meeting: JsonObject
    rows: dict[Endpoint, list[JsonObject]]

    def raw(self) -> RawSession:
        return RawSession(self.session, self.meeting, self.rows)

    def driver_rows(self, endpoint: Endpoint, driver_number: int) -> list[JsonObject]:
        return [row for row in self.rows[endpoint] if row["driver_number"] == driver_number]


def sample(session_key: str) -> Sample:
    """A real session of the 2024 Bahrain Grand Prix, trimmed to four drivers."""
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))[session_key]
    rows = {Endpoint(endpoint): endpoint_rows for endpoint, endpoint_rows in data["rows"].items()}
    return Sample(data["session"], data["meeting"], rows)
