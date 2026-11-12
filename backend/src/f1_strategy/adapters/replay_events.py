"""The wire form of replayed events: what the stream stores and what the browser receives.

One model per event kind, told apart by `kind`. Field names and nulls are the clean model's.
Exact decimals become JSON numbers, which the browser reads as doubles: each of the 1,342,061
replayed numbers of the 2024 season comes back unchanged from a double (measured 2026-11-04);
the long ones, such as a gap of 76.45400000000001, are how a double prints.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from f1_strategy.domain.clean import Compound, Flag, FlagScope, RaceControlCategory
from f1_strategy.domain.replay import Event, EventKind, EventPayload, LapCompleted


class StreamSignal(StrEnum):
    """Stream events that are about the replay itself, not about its session."""

    REPLAY_FAILED = "replay_failed"
    REPLAY_RESET = "replay_reset"


class ReplayFailedEvent(BaseModel):
    kind: Literal[StreamSignal.REPLAY_FAILED] = StreamSignal.REPLAY_FAILED
    message: str


class ReplayResetEvent(BaseModel):
    """The replay moved to the start of a lap: what was built is dropped, and the events that
    follow rebuild the session as it was at `session_s`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[StreamSignal.REPLAY_RESET] = StreamSignal.REPLAY_RESET
    lap_number: int
    session_s: float = Field(description="Seconds since the session's first event")


class _Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    at: AwareDatetime


class RaceControlEvent(_Event):
    kind: Literal[EventKind.RACE_CONTROL] = EventKind.RACE_CONTROL
    seq: int
    category: RaceControlCategory
    flag: Flag | None
    scope: FlagScope | None
    sector: int | None
    driver_number: int | None
    lap_number: int | None
    qualifying_phase: int | None
    message: str


class WeatherEvent(_Event):
    kind: Literal[EventKind.WEATHER] = EventKind.WEATHER
    air_temperature: float
    track_temperature: float
    humidity: float
    pressure: float
    rainfall: bool
    wind_speed: float
    wind_direction: int


class PitEvent(_Event):
    kind: Literal[EventKind.PIT] = EventKind.PIT
    driver_number: int
    lap_number: int
    lane_duration: float | None
    stop_duration: float | None


class LapEvent(_Event):
    kind: Literal[EventKind.LAP] = EventKind.LAP
    driver_number: int
    lap_number: int
    lap_duration: float | None
    duration_sector_1: float | None
    duration_sector_2: float | None
    duration_sector_3: float | None
    i1_speed: int | None
    i2_speed: int | None
    st_speed: int | None
    is_pit_out_lap: bool
    compound: Compound | None
    tyre_age_laps: int | None


class PositionEvent(_Event):
    kind: Literal[EventKind.POSITION] = EventKind.POSITION
    driver_number: int
    position: int


class IntervalEvent(_Event):
    kind: Literal[EventKind.INTERVAL] = EventKind.INTERVAL
    driver_number: int
    gap_to_leader_s: float | None
    gap_to_leader_laps: int | None
    interval_s: float | None
    interval_laps: int | None


class OvertakeEvent(_Event):
    kind: Literal[EventKind.OVERTAKE] = EventKind.OVERTAKE
    overtaking_driver_number: int
    overtaken_driver_number: int
    position: int


class TeamRadioEvent(_Event):
    kind: Literal[EventKind.TEAM_RADIO] = EventKind.TEAM_RADIO
    driver_number: int
    recording_url: str


type ReplayEvent = Annotated[
    RaceControlEvent
    | WeatherEvent
    | PitEvent
    | LapEvent
    | PositionEvent
    | IntervalEvent
    | OvertakeEvent
    | TeamRadioEvent,
    Field(discriminator="kind"),
]


_MODEL_OF_KIND: dict[EventKind, type[_Event]] = {
    EventKind.RACE_CONTROL: RaceControlEvent,
    EventKind.WEATHER: WeatherEvent,
    EventKind.PIT: PitEvent,
    EventKind.LAP: LapEvent,
    EventKind.POSITION: PositionEvent,
    EventKind.INTERVAL: IntervalEvent,
    EventKind.OVERTAKE: OvertakeEvent,
    EventKind.TEAM_RADIO: TeamRadioEvent,
}

_WIRE_ONLY_FIELDS = frozenset({"kind", "at"})


def wire_event(event: Event) -> _Event:
    """The event's model, each field read from the clean row of the same name; pydantic checks
    every value and turns decimals into numbers."""
    model = _MODEL_OF_KIND[event.kind]
    row = _row_fields(event.payload)
    values = {name: row[name] for name in model.model_fields if name not in _WIRE_ONLY_FIELDS}
    return model.model_validate({"at": event.at, **values})


def _row_fields(payload: EventPayload) -> dict[str, object]:
    if isinstance(payload, LapCompleted):
        return {**vars(payload.lap), **vars(payload)}
    return dict(vars(payload))
