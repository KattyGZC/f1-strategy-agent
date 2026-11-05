import json
from dataclasses import asdict
from decimal import Decimal

import pytest
from pydantic import TypeAdapter

from f1_strategy.adapters.replay_events import ReplayEvent, wire_event
from f1_strategy.domain.clean import clean_session
from f1_strategy.domain.replay import Event, EventKind, LapCompleted, timeline
from tests.samples import QUALIFYING, RACE, sample

WIRE = TypeAdapter(ReplayEvent)


def events(key: str) -> tuple[Event, ...]:
    return timeline(clean_session(sample(key).raw())).events


def source_fields(event: Event) -> dict[str, object]:
    payload = event.payload
    if isinstance(payload, LapCompleted):
        fields = {**asdict(payload.lap), **asdict(payload)}
        del fields["lap"]
    else:
        fields = asdict(payload)
    return {
        name: float(value) if isinstance(value, Decimal) else value
        for name, value in fields.items()
    }


def test_the_real_sessions_hold_every_kind_of_event() -> None:
    kinds = {event.kind for key in (RACE, QUALIFYING) for event in events(key)}

    assert kinds == set(EventKind)


@pytest.mark.parametrize("key", [RACE, QUALIFYING])
def test_every_wire_field_is_its_clean_value(key: str) -> None:
    for event in events(key):
        wired = wire_event(event).model_dump()

        assert wired.pop("kind") == event.kind
        assert wired.pop("at") == event.at
        source = source_fields(event)
        assert wired == {name: source[name] for name in wired}, event


@pytest.mark.parametrize("key", [RACE, QUALIFYING])
def test_the_json_of_an_event_parses_back_to_the_same_event(key: str) -> None:
    for event in events(key):
        wired = wire_event(event)

        assert WIRE.validate_json(wired.model_dump_json()) == wired


def test_numbers_are_json_numbers() -> None:
    lap = next(event for event in events(RACE) if isinstance(event.payload, LapCompleted))

    document = json.loads(wire_event(lap).model_dump_json())

    assert isinstance(document["lap_duration"], float)
    assert document["kind"] == "lap"
