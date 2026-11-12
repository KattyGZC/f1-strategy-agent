import random
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

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
from f1_strategy.domain.replay import (
    Event,
    EventKind,
    LapCompleted,
    Timeline,
    still_current,
    timeline,
)
from tests.replay_rows import Rows
from tests.samples import QUALIFYING, RACE, sample

SESSION = 9472
T0 = datetime(2024, 3, 2, 15, tzinfo=UTC)


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
        SESSION,
        at,
        Decimal(25),
        Decimal(30),
        Decimal(50),
        Decimal(1013),
        rainfall=False,
        wind_speed=Decimal(1),
        wind_direction=90,
    )


def interval(driver_number: int, at: datetime = T0) -> Interval:
    return Interval(SESSION, driver_number, at, Decimal(1), None, Decimal(1), None)


def pit(driver_number: int, lap_number: int, at: datetime = T0) -> Pit:
    return Pit(SESSION, driver_number, lap_number, at, None, None)


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
    assert timeline(Rows()) == Timeline((), 0, {})


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


def test_a_lap_starts_at_its_earliest_start_among_drivers() -> None:
    rows = Rows(
        laps=[
            lap(16, 2, date_start=T0 + timedelta(seconds=1.2)),
            lap(1, 2, date_start=T0),
            lap(44, 2, date_start=T0 + timedelta(seconds=3)),
            lap(1, 1, date_start=T0 - timedelta(seconds=95)),
        ]
    )

    assert timeline(rows).lap_starts == {1: T0 - timedelta(seconds=95), 2: T0}


def test_a_lap_with_a_start_and_no_duration_still_starts() -> None:
    rows = Rows(laps=[lap(1, 1, lap_duration=None)])

    result = timeline(rows)

    assert result.events == ()
    assert result.lap_starts == {1: T0}


def test_a_lap_no_driver_has_a_start_for_has_no_start() -> None:
    rows = Rows(laps=[lap(1, 4, date_start=None), lap(16, 4, date_start=None), lap(1, 5)])

    assert timeline(rows).lap_starts == {5: T0}


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


def test_the_last_lap_of_a_stint_carries_its_tyre() -> None:
    rows = Rows(laps=[lap(1, 10)], stints=[stint(1, 1, (1, 10), tyre_age_at_start=2)])

    assert only_lap(rows) == LapCompleted(lap(1, 10), Compound.SOFT, 11)


def test_a_newer_stint_without_a_start_leaves_the_lap_to_an_older_one() -> None:
    no_start = Stint(SESSION, 1, 2, Compound.HARD, None, 5, 0)
    rows = Rows(laps=[lap(1, 3)], stints=[stint(1, 1, (1, 10), compound=Compound.MEDIUM), no_start])

    assert only_lap(rows) == LapCompleted(lap(1, 3), Compound.MEDIUM, 2)


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


# Few instants and drivers, so most rows tie on the instant and the kind and only the row key
# decides. Each table is unique on its order key, as the clean schema makes it.
INSTANTS = st.sampled_from([T0 + timedelta(seconds=offset_s) for offset_s in range(3)])
DRIVERS = st.sampled_from([1, 16, 44])


TYING_ROWS = st.builds(
    Rows,
    laps=st.lists(
        st.builds(
            lap,
            DRIVERS,
            st.integers(1, 3),
            date_start=INSTANTS,
            lap_duration=st.sampled_from([Decimal(1), Decimal(2)]),
        ),
        unique_by=lambda row: (row.driver_number, row.lap_number),
    ),
    positions=st.lists(
        st.builds(position, DRIVERS, INSTANTS), unique_by=lambda row: (row.driver_number, row.date)
    ),
    race_control=st.lists(
        st.builds(race_control, st.integers(0, 5), INSTANTS), unique_by=lambda row: row.seq
    ),
    weather=st.lists(st.builds(weather, INSTANTS), unique_by=lambda row: row.date),
    overtakes=st.lists(
        st.builds(Overtake, st.just(SESSION), INSTANTS, DRIVERS, DRIVERS, st.just(1)),
        unique_by=lambda row: (row.date, row.overtaking_driver_number, row.overtaken_driver_number),
    ),
    team_radio=st.lists(
        st.builds(TeamRadio, st.just(SESSION), DRIVERS, INSTANTS, st.just("u")),
        unique_by=lambda row: (row.driver_number, row.date),
    ),
    intervals=st.lists(
        st.builds(interval, DRIVERS, INSTANTS), unique_by=lambda row: (row.driver_number, row.date)
    ),
    pits=st.lists(
        st.builds(pit, DRIVERS, st.integers(1, 3), INSTANTS),
        unique_by=(
            lambda row: (row.driver_number, row.lap_number),
            lambda row: (row.driver_number, row.date),
        ),
    ),
)


@given(rows=TYING_ROWS, data=st.data())
def test_any_arrival_order_gives_the_same_timeline(rows: Rows, data: st.DataObject) -> None:
    arrived = Rows(
        **{name: data.draw(st.permutations(table)) for name, table in vars(rows).items()}
    )

    assert timeline(arrived) == timeline(rows)


def test_nothing_is_current_among_no_events() -> None:
    assert still_current(()) == ()


def test_a_later_value_of_the_same_driver_replaces_an_earlier_one() -> None:
    later = T0 + timedelta(seconds=1)
    events = timeline(
        Rows(
            positions=[position(1), position(16), position(1, later)],
            intervals=[interval(1), interval(1, later)],
            laps=[lap(1, 1), lap(1, 2, date_start=later)],
            weather=[weather(), weather(later)],
        )
    ).events

    kept = [events[index].payload for index in still_current(events)]

    assert kept == [
        position(16),
        weather(later),
        position(1, later),
        interval(1, later),
        LapCompleted(lap(1, 2, date_start=later), None, None),
    ]


def test_records_stay_whatever_comes_after_them() -> None:
    later = T0 + timedelta(seconds=1)
    rows = Rows(
        race_control=[race_control(0), race_control(1, later)],
        pits=[pit(1, 1), pit(1, 2, later)],
        overtakes=[Overtake(SESSION, T0, 1, 16, 2), Overtake(SESSION, later, 1, 16, 1)],
        team_radio=[TeamRadio(SESSION, 1, T0, "a"), TeamRadio(SESSION, 1, later, "b")],
    )
    events = timeline(rows).events

    assert still_current(events) == tuple(range(len(events)))


def _value_of(event: Event) -> tuple[EventKind, int | None] | None:
    """What an event states the latest value of, as ADR 0013 lists them."""
    match event.payload:
        case Position() | Interval():
            return event.kind, event.payload.driver_number
        case LapCompleted():
            return event.kind, event.payload.lap.driver_number
        case Weather():
            return event.kind, None
        case _:
            return None


@given(rows=TYING_ROWS)
def test_an_event_stays_current_unless_a_later_one_states_the_same_value(rows: Rows) -> None:
    events = timeline(rows).events

    expected = tuple(
        index
        for index, event in enumerate(events)
        if _value_of(event) is None
        or all(_value_of(later) != _value_of(event) for later in events[index + 1 :])
    )

    assert still_current(events) == expected
    if events:
        assert expected[-1] == len(events) - 1
