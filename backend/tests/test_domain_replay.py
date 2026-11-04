import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest

from f1_strategy.domain.clean import (
    CleanSession,
    Compound,
    Interval,
    Lap,
    Overtake,
    Pit,
    Position,
    RaceControl,
    RaceControlCategory,
    Stint,
    TeamRadio,
    Weather,
    clean_session,
)
from f1_strategy.domain.replay import EventKind, LapCompleted, Timeline, timeline
from tests.samples import QUALIFYING, RACE, sample

SESSION = 9472
T0 = datetime(2024, 3, 2, 15, tzinfo=UTC)


@dataclass
class Rows:
    laps: list[Lap] = field(default_factory=list)
    stints: list[Stint] = field(default_factory=list)
    pits: list[Pit] = field(default_factory=list)
    intervals: list[Interval] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    race_control: list[RaceControl] = field(default_factory=list)
    weather: list[Weather] = field(default_factory=list)
    overtakes: list[Overtake] = field(default_factory=list)
    team_radio: list[TeamRadio] = field(default_factory=list)


def lap(
    driver_number: int,
    lap_number: int,
    *,
    date_start: datetime | None = T0,
    lap_duration: Decimal | None = Decimal("92.5"),
) -> Lap:
    return Lap(
        SESSION, driver_number, lap_number, date_start, lap_duration,
        None, None, None, None, None, None, is_pit_out_lap=False,
    )  # fmt: skip


def stint(
    driver_number: int,
    stint_number: int,
    laps: tuple[int, int] | None,
    *,
    compound: Compound = Compound.SOFT,
    tyre_age_at_start: int = 0,
) -> Stint:
    lap_start, lap_end = laps or (None, None)
    return Stint(
        SESSION, driver_number, stint_number, compound, lap_start, lap_end, tyre_age_at_start
    )


def position(driver_number: int, at: datetime = T0) -> Position:
    return Position(SESSION, driver_number, at, 1)


def race_control(seq: int, at: datetime = T0) -> RaceControl:
    return RaceControl(
        SESSION, seq, at, RaceControlCategory.OTHER, None, None, None, None, None, None, "msg"
    )


def weather(at: datetime = T0) -> Weather:
    return Weather(
        SESSION, at, Decimal(25), Decimal(30), Decimal(50), Decimal(1013), False, Decimal(1), 90
    )


def only_lap(rows: Rows) -> LapCompleted:
    (event,) = timeline(rows).events
    assert isinstance(event.payload, LapCompleted)
    return event.payload


def shuffled(clean: CleanSession, seed: int) -> Rows:
    shuffler = random.Random(seed)  # noqa: S311 - a test shuffle, not a secret
    tables = {
        name: shuffler.sample(list(rows), len(rows))
        for name, rows in vars(clean).items()
        if name in Rows.__dataclass_fields__
    }
    return Rows(**tables)


def test_an_empty_session_has_an_empty_timeline() -> None:
    assert timeline(Rows()) == Timeline((), 0)


def test_a_lap_happens_when_it_ends() -> None:
    rows = Rows(laps=[lap(1, 3, lap_duration=Decimal("91.234"))])

    (event,) = timeline(rows).events

    assert event.at == T0 + timedelta(seconds=91, microseconds=234_000)
    assert event.kind is EventKind.LAP


@pytest.mark.parametrize(
    "missing",
    [
        lap(1, 1, lap_duration=None),
        lap(1, 1, date_start=None),
        lap(1, 1, date_start=None, lap_duration=None),
    ],
)
def test_a_lap_without_an_end_is_counted_not_emitted(missing: Lap) -> None:
    rows = Rows(laps=[missing, lap(1, 2)])

    result = timeline(rows)

    assert result.laps_without_instant == 1
    assert [event.payload for event in result.events] == [LapCompleted(lap(1, 2), None, None)]


def test_a_lap_carries_its_stint_tyre_and_age() -> None:
    rows = Rows(
        laps=[lap(1, 7)],
        stints=[stint(1, 1, (5, 20), compound=Compound.MEDIUM, tyre_age_at_start=3)],
    )

    assert only_lap(rows) == LapCompleted(lap(1, 7), Compound.MEDIUM, 5)


@pytest.mark.parametrize("stint_order", [(0, 1), (1, 0)])
def test_a_shared_boundary_lap_belongs_to_the_new_stint(stint_order: tuple[int, int]) -> None:
    stints = [stint(1, 1, (1, 15)), stint(1, 2, (15, 40), compound=Compound.HARD)]
    rows = Rows(laps=[lap(1, 15)], stints=[stints[index] for index in stint_order])

    assert only_lap(rows) == LapCompleted(lap(1, 15), Compound.HARD, 0)


def test_a_lap_no_stint_covers_has_no_tyre() -> None:
    rows = Rows(
        laps=[lap(1, 21)],
        stints=[stint(1, 1, (1, 20)), stint(1, 2, None), stint(16, 1, (1, 57))],
    )

    assert only_lap(rows) == LapCompleted(lap(1, 21), None, None)


def test_events_of_one_instant_follow_the_kind_rank() -> None:
    ended_at_t0 = lap(1, 2, date_start=T0 - timedelta(seconds=90), lap_duration=Decimal(90))
    rows = Rows(
        team_radio=[TeamRadio(SESSION, 1, T0, "https://example.org/radio.mp3")],
        overtakes=[Overtake(SESSION, T0, 1, 16, 1)],
        intervals=[Interval(SESSION, 1, T0, Decimal(0), None, Decimal(0), None)],
        positions=[position(1)],
        laps=[ended_at_t0],
        pits=[Pit(SESSION, 1, 2, T0, None, None)],
        weather=[weather()],
        race_control=[race_control(0)],
    )

    kinds = [event.kind for event in timeline(rows).events]

    assert kinds == list(EventKind)


def test_events_of_one_instant_and_kind_follow_the_row_key() -> None:
    rows = Rows(
        positions=[position(44), position(1), position(16)],
        race_control=[race_control(2), race_control(0), race_control(1)],
        overtakes=[Overtake(SESSION, T0, 16, 44, 2), Overtake(SESSION, T0, 1, 44, 1)],
    )

    assert [event.payload for event in timeline(rows).events] == [
        race_control(0),
        race_control(1),
        race_control(2),
        position(1),
        position(16),
        position(44),
        Overtake(SESSION, T0, 1, 44, 1),
        Overtake(SESSION, T0, 16, 44, 2),
    ]


def test_an_earlier_instant_comes_first_whatever_its_kind() -> None:
    later = T0 + timedelta(milliseconds=1)
    rows = Rows(race_control=[race_control(0, later)], team_radio=[TeamRadio(SESSION, 1, T0, "u")])

    assert [event.kind for event in timeline(rows).events] == [
        EventKind.TEAM_RADIO,
        EventKind.RACE_CONTROL,
    ]


@pytest.mark.parametrize("key", [RACE, QUALIFYING])
def test_every_row_of_a_real_session_is_one_event_in_order(key: str) -> None:
    clean = clean_session(sample(key).raw())

    result = timeline(clean)

    counts = Counter(event.kind for event in result.events)
    laps_without_instant = sum(
        row.date_start is None or row.lap_duration is None for row in clean.laps
    )
    assert counts == Counter(
        {
            EventKind.LAP: len(clean.laps) - laps_without_instant,
            EventKind.RACE_CONTROL: len(clean.race_control),
            EventKind.WEATHER: len(clean.weather),
            EventKind.PIT: len(clean.pits),
            EventKind.POSITION: len(clean.positions),
            EventKind.INTERVAL: len(clean.intervals),
            EventKind.OVERTAKE: len(clean.overtakes),
            EventKind.TEAM_RADIO: len(clean.team_radio),
        }
    )
    assert result.laps_without_instant == laps_without_instant
    assert all(earlier.at <= later.at for earlier, later in pairwise(result.events))


def test_the_real_race_has_tyres_on_its_laps() -> None:
    clean = clean_session(sample(RACE).raw())

    laps = [
        event.payload for event in timeline(clean).events if isinstance(event.payload, LapCompleted)
    ]

    assert laps
    assert all(payload.compound is not None for payload in laps)


@pytest.mark.parametrize("seed", range(5))
def test_the_order_of_rows_does_not_change_the_timeline(seed: int) -> None:
    clean = clean_session(sample(RACE).raw())

    assert timeline(shuffled(clean, seed)) == timeline(clean)
