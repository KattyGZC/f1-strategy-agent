"""The clean model of Race and Qualifying sessions (ADR 0008).

Closed sets, nulls and cross-column rules are the ones measured on the 2024 season.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"

TYPES = (
    "CREATE TYPE circuit_type AS ENUM ('Permanent', 'Temporary - Street', 'Temporary - Road')",
    "CREATE TYPE session_type AS ENUM ('Practice', 'Qualifying', 'Race')",
    "CREATE TYPE session_name AS ENUM ('Qualifying', 'Sprint Qualifying', 'Race', 'Sprint')",
    "CREATE TYPE compound AS ENUM ('SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET', 'UNKNOWN')",
    """CREATE TYPE race_control_category AS ENUM (
        'Flag', 'Other', 'SessionStatus', 'Drs', 'SafetyCar', 'CarEvent'
    )""",
    """CREATE TYPE flag AS ENUM (
        'GREEN', 'YELLOW', 'DOUBLE YELLOW', 'RED', 'BLUE', 'CLEAR', 'CHEQUERED', 'BLACK AND WHITE'
    )""",
    "CREATE TYPE flag_scope AS ENUM ('Track', 'Sector', 'Driver')",
)

TABLES = (
    """
    CREATE TABLE meeting (
        meeting_key integer PRIMARY KEY CHECK (meeting_key > 0),
        year smallint NOT NULL,
        meeting_name text NOT NULL,
        meeting_official_name text NOT NULL,
        circuit_key integer NOT NULL,
        circuit_short_name text NOT NULL,
        circuit_type circuit_type NOT NULL,
        country_key integer NOT NULL,
        country_code text NOT NULL,
        country_name text NOT NULL,
        location text NOT NULL,
        gmt_offset interval NOT NULL,
        date_start timestamptz NOT NULL,
        date_end timestamptz NOT NULL,
        is_cancelled boolean NOT NULL,
        CHECK (date_start <= date_end)
    )
    """,
    """
    CREATE TABLE session (
        session_key integer PRIMARY KEY CHECK (session_key > 0),
        meeting_key integer NOT NULL REFERENCES meeting,
        session_type session_type NOT NULL,
        session_name session_name NOT NULL,
        date_start timestamptz NOT NULL,
        date_end timestamptz NOT NULL,
        CHECK (date_start <= date_end)
    )
    """,
    "CREATE INDEX session_meeting ON session (meeting_key)",
    """
    CREATE TABLE driver_session (
        session_key integer NOT NULL REFERENCES session ON DELETE CASCADE,
        driver_number integer NOT NULL CHECK (driver_number > 0),
        full_name text NOT NULL,
        first_name text NOT NULL,
        last_name text NOT NULL,
        broadcast_name text NOT NULL,
        name_acronym text NOT NULL,
        country_code text,
        team_name text NOT NULL,
        team_colour text NOT NULL CHECK (team_colour ~ '^[0-9A-Fa-f]{6}$'),
        headshot_url text,
        PRIMARY KEY (session_key, driver_number)
    )
    """,
    """
    CREATE TABLE lap (
        session_key integer NOT NULL,
        driver_number integer NOT NULL,
        lap_number integer NOT NULL CHECK (lap_number > 0),
        date_start timestamptz,
        lap_duration numeric CHECK (lap_duration > 0),
        duration_sector_1 numeric CHECK (duration_sector_1 > 0),
        duration_sector_2 numeric CHECK (duration_sector_2 > 0),
        duration_sector_3 numeric CHECK (duration_sector_3 > 0),
        i1_speed integer CHECK (i1_speed > 0),
        i2_speed integer CHECK (i2_speed > 0),
        st_speed integer CHECK (st_speed > 0),
        is_pit_out_lap boolean NOT NULL,
        PRIMARY KEY (session_key, driver_number, lap_number),
        FOREIGN KEY (session_key, driver_number) REFERENCES driver_session ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE stint (
        session_key integer NOT NULL,
        driver_number integer NOT NULL,
        stint_number integer NOT NULL CHECK (stint_number > 0),
        compound compound NOT NULL,
        lap_start integer CHECK (lap_start > 0),
        lap_end integer,
        tyre_age_at_start integer NOT NULL CHECK (tyre_age_at_start >= 0),
        PRIMARY KEY (session_key, driver_number, stint_number),
        FOREIGN KEY (session_key, driver_number) REFERENCES driver_session ON DELETE CASCADE,
        CONSTRAINT stint_laps_whole CHECK (num_nulls(lap_start, lap_end) IN (0, 2)),
        CONSTRAINT stint_laps_ordered CHECK (lap_start <= lap_end)
    )
    """,
    """
    CREATE TABLE pit (
        session_key integer NOT NULL,
        driver_number integer NOT NULL,
        lap_number integer NOT NULL CHECK (lap_number > 0),
        date timestamptz NOT NULL,
        lane_duration numeric CHECK (lane_duration > 0),
        stop_duration numeric CHECK (stop_duration > 0),
        PRIMARY KEY (session_key, driver_number, lap_number),
        UNIQUE (session_key, driver_number, date),
        FOREIGN KEY (session_key, driver_number) REFERENCES driver_session ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE interval (
        session_key integer NOT NULL,
        driver_number integer NOT NULL,
        date timestamptz NOT NULL,
        gap_to_leader_s numeric CHECK (gap_to_leader_s >= 0),
        gap_to_leader_laps integer CHECK (gap_to_leader_laps > 0),
        interval_s numeric CHECK (interval_s >= 0),
        interval_laps integer CHECK (interval_laps > 0),
        PRIMARY KEY (session_key, driver_number, date),
        FOREIGN KEY (session_key, driver_number) REFERENCES driver_session ON DELETE CASCADE,
        CONSTRAINT interval_gap_one_unit CHECK (
            num_nonnulls(gap_to_leader_s, gap_to_leader_laps) <= 1
        ),
        CONSTRAINT interval_one_unit CHECK (num_nonnulls(interval_s, interval_laps) <= 1)
    )
    """,
    """
    CREATE TABLE position (
        session_key integer NOT NULL,
        driver_number integer NOT NULL,
        date timestamptz NOT NULL,
        position integer NOT NULL CHECK (position > 0),
        PRIMARY KEY (session_key, driver_number, date),
        FOREIGN KEY (session_key, driver_number) REFERENCES driver_session ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE race_control (
        session_key integer NOT NULL REFERENCES session ON DELETE CASCADE,
        seq integer NOT NULL CHECK (seq >= 0),
        date timestamptz NOT NULL,
        category race_control_category NOT NULL,
        flag flag,
        scope flag_scope,
        sector integer CHECK (sector > 0),
        driver_number integer,
        lap_number integer CHECK (lap_number > 0),
        qualifying_phase integer CHECK (qualifying_phase BETWEEN 1 AND 3),
        message text NOT NULL,
        PRIMARY KEY (session_key, seq),
        FOREIGN KEY (session_key, driver_number) REFERENCES driver_session ON DELETE CASCADE,
        CONSTRAINT race_control_flag CHECK (
            (category = 'Flag') = (flag IS NOT NULL) AND (flag IS NULL) = (scope IS NULL)
        ),
        CONSTRAINT race_control_sector CHECK (
            (scope IS NOT DISTINCT FROM 'Sector') = (sector IS NOT NULL)
        ),
        CONSTRAINT race_control_driver CHECK (scope <> 'Driver' OR driver_number IS NOT NULL)
    )
    """,
    """
    CREATE TABLE weather (
        session_key integer NOT NULL REFERENCES session ON DELETE CASCADE,
        date timestamptz NOT NULL,
        air_temperature numeric NOT NULL,
        track_temperature numeric NOT NULL,
        humidity numeric NOT NULL CHECK (humidity BETWEEN 0 AND 100),
        pressure numeric NOT NULL CHECK (pressure > 0),
        rainfall boolean NOT NULL,
        wind_speed numeric NOT NULL CHECK (wind_speed >= 0),
        wind_direction integer NOT NULL CHECK (wind_direction BETWEEN 0 AND 360),
        PRIMARY KEY (session_key, date)
    )
    """,
    """
    CREATE TABLE session_result (
        session_key integer NOT NULL,
        driver_number integer NOT NULL,
        position integer CHECK (position > 0),
        number_of_laps integer CHECK (number_of_laps >= 0),
        dnf boolean NOT NULL,
        dns boolean NOT NULL,
        dsq boolean NOT NULL,
        duration numeric CHECK (duration > 0),
        gap_to_leader_s numeric CHECK (gap_to_leader_s >= 0),
        gap_to_leader_laps integer CHECK (gap_to_leader_laps > 0),
        points numeric CHECK (points >= 0),
        PRIMARY KEY (session_key, driver_number),
        UNIQUE (session_key, position),
        FOREIGN KEY (session_key, driver_number) REFERENCES driver_session ON DELETE CASCADE,
        CONSTRAINT session_result_one_outcome CHECK (
            dnf::integer + dns::integer + dsq::integer <= 1
        ),
        CONSTRAINT session_result_gap_one_unit CHECK (
            num_nonnulls(gap_to_leader_s, gap_to_leader_laps) <= 1
        )
    )
    """,
    """
    CREATE TABLE qualifying_phase_result (
        session_key integer NOT NULL,
        driver_number integer NOT NULL,
        phase integer NOT NULL CHECK (phase BETWEEN 1 AND 3),
        duration numeric CHECK (duration > 0),
        gap_to_leader_s numeric CHECK (gap_to_leader_s >= 0),
        PRIMARY KEY (session_key, driver_number, phase),
        FOREIGN KEY (session_key, driver_number) REFERENCES session_result ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE starting_grid (
        session_key integer NOT NULL,
        driver_number integer NOT NULL,
        position integer NOT NULL CHECK (position > 0),
        lap_duration numeric CHECK (lap_duration > 0),
        PRIMARY KEY (session_key, driver_number),
        UNIQUE (session_key, position),
        FOREIGN KEY (session_key, driver_number) REFERENCES driver_session ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE overtake (
        session_key integer NOT NULL,
        date timestamptz NOT NULL,
        overtaking_driver_number integer NOT NULL,
        overtaken_driver_number integer NOT NULL,
        position integer NOT NULL CHECK (position > 0),
        PRIMARY KEY (session_key, date, overtaking_driver_number, overtaken_driver_number),
        FOREIGN KEY (session_key, overtaking_driver_number)
            REFERENCES driver_session ON DELETE CASCADE,
        FOREIGN KEY (session_key, overtaken_driver_number)
            REFERENCES driver_session ON DELETE CASCADE,
        CHECK (overtaking_driver_number <> overtaken_driver_number)
    )
    """,
    """
    CREATE TABLE team_radio (
        session_key integer NOT NULL,
        driver_number integer NOT NULL,
        date timestamptz NOT NULL,
        recording_url text NOT NULL,
        PRIMARY KEY (session_key, driver_number, date),
        FOREIGN KEY (session_key, driver_number) REFERENCES driver_session ON DELETE CASCADE
    )
    """,
)


def upgrade() -> None:
    for statement in (*TYPES, *TABLES):
        op.execute(statement)
