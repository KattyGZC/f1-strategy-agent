from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import errors

from f1_strategy.adapters.migrate import upgrade
from tests.postgres import CONNECT_TIMEOUT_S, fresh_database

SESSION_KEY = 9472
DRIVER = 1
OTHER_DRIVER = 11
START = datetime(2024, 3, 2, 15, tzinfo=UTC)

type Row = dict[str, object]

MEETING: Row = {
    "meeting_key": 1229,
    "year": 2024,
    "meeting_name": "Bahrain Grand Prix",
    "meeting_official_name": "FORMULA 1 GULF AIR BAHRAIN GRAND PRIX 2024",
    "circuit_key": 63,
    "circuit_short_name": "Sakhir",
    "circuit_type": "Permanent",
    "country_key": 36,
    "country_code": "BRN",
    "country_name": "Bahrain",
    "location": "Sakhir",
    "gmt_offset": timedelta(hours=3),
    "date_start": START - timedelta(days=2),
    "date_end": START + timedelta(hours=2),
    "is_cancelled": False,
}
SESSION: Row = {
    "session_key": SESSION_KEY,
    "meeting_key": 1229,
    "session_type": "Race",
    "session_name": "Race",
    "date_start": START,
    "date_end": START + timedelta(hours=2),
}


def driver(number: int) -> Row:
    return {
        "session_key": SESSION_KEY,
        "driver_number": number,
        "full_name": f"Driver {number}",
        "first_name": "Driver",
        "last_name": str(number),
        "broadcast_name": f"D {number}",
        "name_acronym": f"D{number:02}",
        "country_code": None,
        "team_name": "Team",
        "team_colour": "3671C6",
        "headshot_url": None,
    }


VALID: dict[str, Row] = {
    "lap": {
        "session_key": SESSION_KEY,
        "driver_number": DRIVER,
        "lap_number": 1,
        "date_start": None,
        "lap_duration": None,
        "duration_sector_1": None,
        "duration_sector_2": 30.1,
        "duration_sector_3": 31.2,
        "i1_speed": None,
        "i2_speed": 280,
        "st_speed": 300,
        "is_pit_out_lap": False,
    },
    "stint": {
        "session_key": SESSION_KEY,
        "driver_number": DRIVER,
        "stint_number": 1,
        "compound": "SOFT",
        "lap_start": 1,
        "lap_end": 17,
        "tyre_age_at_start": 3,
    },
    "pit": {
        "session_key": SESSION_KEY,
        "driver_number": DRIVER,
        "lap_number": 17,
        "date": START + timedelta(minutes=30),
        "lane_duration": None,
        "stop_duration": None,
    },
    "interval": {
        "session_key": SESSION_KEY,
        "driver_number": DRIVER,
        "date": START,
        "gap_to_leader_s": None,
        "gap_to_leader_laps": 1,
        "interval_s": 1.234,
        "interval_laps": None,
    },
    "position": {
        "session_key": SESSION_KEY,
        "driver_number": DRIVER,
        "date": START,
        "position": 1,
    },
    "race_control": {
        "session_key": SESSION_KEY,
        "seq": 0,
        "date": START,
        "category": "Flag",
        "flag": "YELLOW",
        "scope": "Sector",
        "sector": 7,
        "driver_number": None,
        "lap_number": 3,
        "qualifying_phase": None,
        "message": "YELLOW IN TRACK SECTOR 7",
    },
    "weather": {
        "session_key": SESSION_KEY,
        "date": START,
        "air_temperature": 18.9,
        "track_temperature": 26.5,
        "humidity": 46.0,
        "pressure": 1017.0,
        "rainfall": False,
        "wind_speed": 0.7,
        "wind_direction": 360,
    },
    "session_result": {
        "session_key": SESSION_KEY,
        "driver_number": DRIVER,
        "position": None,
        "number_of_laps": 0,
        "dnf": True,
        "dns": False,
        "dsq": False,
        "duration": None,
        "gap_to_leader_s": None,
        "gap_to_leader_laps": None,
        "points": 0,
    },
    "starting_grid": {
        "session_key": SESSION_KEY,
        "driver_number": DRIVER,
        "position": 1,
        "lap_duration": None,
    },
    "overtake": {
        "session_key": SESSION_KEY,
        "date": START,
        "overtaking_driver_number": DRIVER,
        "overtaken_driver_number": OTHER_DRIVER,
        "position": 1,
    },
    "team_radio": {
        "session_key": SESSION_KEY,
        "driver_number": DRIVER,
        "date": START,
        "recording_url": "https://livetiming.formula1.com/radio.mp3",
    },
}
ROWS: dict[str, Row] = {**VALID, "driver_session": driver(44)}
QUALIFYING_PHASE: Row = {
    "session_key": SESSION_KEY,
    "driver_number": DRIVER,
    "phase": 1,
    "duration": 91.0,
    "gap_to_leader_s": 0.0,
}


@pytest.fixture(scope="module")
def postgres_uri(postgres_server_uri: str) -> str:
    uri = fresh_database(postgres_server_uri)
    upgrade(uri, CONNECT_TIMEOUT_S)
    return uri


@pytest.fixture
def connection(postgres_uri: str) -> Iterator[psycopg.Connection]:
    """A connection with one session and two drivers, rolled back after the test."""
    with psycopg.connect(postgres_uri, connect_timeout=CONNECT_TIMEOUT_S) as connection:
        insert(connection, "meeting", MEETING)
        insert(connection, "session", SESSION)
        insert(connection, "driver_session", driver(DRIVER))
        insert(connection, "driver_session", driver(OTHER_DRIVER))
        yield connection
        connection.rollback()


def insert(connection: psycopg.Connection, table: str, row: Row) -> None:
    columns = ", ".join(row)
    values = ", ".join(f"%({column})s" for column in row)
    connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({values})", row)  # noqa: S608


def count(connection: psycopg.Connection, table: str) -> int:
    row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
    assert row is not None
    return int(row[0])


@pytest.mark.parametrize("table", list(VALID))
def test_a_measured_row_is_accepted(connection: psycopg.Connection, table: str) -> None:
    insert(connection, table, VALID[table])

    assert count(connection, table) == 1


def test_qualifying_phases_belong_to_a_result(connection: psycopg.Connection) -> None:
    with pytest.raises(errors.ForeignKeyViolation):
        insert(connection, "qualifying_phase_result", QUALIFYING_PHASE)


def test_deleting_a_session_deletes_everything_it_owns(connection: psycopg.Connection) -> None:
    for table, row in VALID.items():
        insert(connection, table, row)
    insert(connection, "qualifying_phase_result", QUALIFYING_PHASE)

    connection.execute("DELETE FROM session WHERE session_key = %s", [SESSION_KEY])

    owned = [*VALID, "qualifying_phase_result", "driver_session"]
    assert {table: count(connection, table) for table in owned} == dict.fromkeys(owned, 0)
    assert count(connection, "meeting") == 1


@pytest.mark.parametrize(
    ("table", "changes", "error", "constraint"),
    [
        pytest.param(
            "stint",
            {"compound": "HYPERSOFT"},
            errors.InvalidTextRepresentation,
            None,
            id="compound outside the closed set",
        ),
        pytest.param(
            "lap",
            {"driver_number": 99},
            errors.ForeignKeyViolation,
            "lap_session_key_driver_number_fkey",
            id="lap of a driver not in the session",
        ),
        pytest.param(
            "lap",
            {"lap_duration": 0},
            errors.CheckViolation,
            "lap_lap_duration_check",
            id="lap of no duration",
        ),
        pytest.param(
            "stint",
            {"lap_end": None},
            errors.CheckViolation,
            "stint_laps_whole",
            id="stint with half a lap range",
        ),
        pytest.param(
            "stint",
            {"lap_start": 18},
            errors.CheckViolation,
            "stint_laps_ordered",
            id="stint ending before it starts",
        ),
        pytest.param(
            "interval",
            {"gap_to_leader_s": 1.5},
            errors.CheckViolation,
            "interval_gap_one_unit",
            id="gap in seconds and in laps",
        ),
        pytest.param(
            "interval",
            {"interval_laps": 1},
            errors.CheckViolation,
            "interval_one_unit",
            id="interval in seconds and in laps",
        ),
        pytest.param(
            "race_control",
            {"flag": None},
            errors.CheckViolation,
            "race_control_flag",
            id="flag message without a flag",
        ),
        pytest.param(
            "race_control",
            {"category": "Other", "flag": None, "scope": None},
            errors.CheckViolation,
            "race_control_sector",
            id="sector without a sector scope",
        ),
        pytest.param(
            "race_control",
            {"scope": "Driver", "sector": None},
            errors.CheckViolation,
            "race_control_driver",
            id="driver scope without a driver",
        ),
        pytest.param(
            "weather",
            {"humidity": 101},
            errors.CheckViolation,
            "weather_humidity_check",
            id="humidity over 100",
        ),
        pytest.param(
            "session_result",
            {"dns": True},
            errors.CheckViolation,
            "session_result_one_outcome",
            id="DNF and DNS at once",
        ),
        pytest.param(
            "session_result",
            {"gap_to_leader_s": 3.0, "gap_to_leader_laps": 1},
            errors.CheckViolation,
            "session_result_gap_one_unit",
            id="result gap in seconds and in laps",
        ),
        pytest.param(
            "overtake",
            {"overtaken_driver_number": DRIVER},
            errors.CheckViolation,
            "overtake_check",
            id="driver overtaking itself",
        ),
        pytest.param(
            "driver_session",
            {"team_colour": "blue"},
            errors.CheckViolation,
            "driver_session_team_colour_check",
            id="team colour not hex",
        ),
    ],
)
def test_a_row_outside_the_schema_is_rejected(
    connection: psycopg.Connection,
    table: str,
    changes: Row,
    error: type[psycopg.Error],
    constraint: str | None,
) -> None:
    row = {**ROWS[table], **changes}

    with pytest.raises(error) as rejected:
        insert(connection, table, row)

    assert rejected.value.diag.constraint_name == constraint


@pytest.mark.parametrize(
    ("table", "changes", "constraint"),
    [
        pytest.param("lap", {}, "lap_pkey", id="lap twice"),
        pytest.param(
            "pit",
            {"lap_number": 18},
            "pit_session_key_driver_number_date_key",
            id="two pits at one instant",
        ),
        pytest.param(
            "starting_grid",
            {"driver_number": OTHER_DRIVER},
            "starting_grid_session_key_position_key",
            id="two drivers on one grid slot",
        ),
    ],
)
def test_a_natural_key_is_stored_once(
    connection: psycopg.Connection,
    table: str,
    changes: Row,
    constraint: str,
) -> None:
    insert(connection, table, VALID[table])

    with pytest.raises(errors.UniqueViolation) as rejected:
        insert(connection, table, {**VALID[table], **changes})
    assert rejected.value.diag.constraint_name == constraint


def test_unclassified_results_do_not_collide_on_position(connection: psycopg.Connection) -> None:
    insert(connection, "session_result", VALID["session_result"])

    insert(connection, "session_result", {**VALID["session_result"], "driver_number": OTHER_DRIVER})

    assert count(connection, "session_result") == 2
