"""The lap-time model of each race, calibrated on its clean laps (ADR 0014).

Every row cascades from the race's session, so a transform that reloads a session drops its
calibration with it, and the next calibrate run computes it again.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"

TYPES = (
    "CREATE TYPE calibration_status AS ENUM ('calibrated', 'not_calibrated', 'failed')",
    "CREATE TYPE not_calibrated_reason AS ENUM ('no_clean_laps', 'not_identifiable')",
    """CREATE TYPE exclusion_reason AS ENUM (
        'no_duration', 'no_stint', 'not_calibrated_compound', 'first_lap', 'pit_out_lap',
        'pit_in_lap', 'no_start_instant', 'neutralised', 'restart_lap', 'wet_track', 'outlier',
        'compound_too_few_laps', 'driver_too_few_laps'
    )""",
)

TABLES = (
    """
    CREATE TABLE calibration_run (
        session_key integer PRIMARY KEY REFERENCES session ON DELETE CASCADE,
        status calibration_status NOT NULL,
        clean_output_hash text NOT NULL,
        calibration_version text NOT NULL,
        not_calibrated_reason not_calibrated_reason,
        error_message text,
        calibrated_at timestamptz NOT NULL,
        CONSTRAINT not_calibrated_has_reason CHECK (
            (status = 'not_calibrated') = (not_calibrated_reason IS NOT NULL)
        ),
        CONSTRAINT failed_has_error CHECK ((status = 'failed') = (error_message IS NOT NULL))
    )
    """,
    """
    CREATE TABLE calibration (
        session_key integer PRIMARY KEY REFERENCES calibration_run ON DELETE CASCADE,
        race_laps integer NOT NULL CHECK (race_laps > 0),
        residual_rmse_s numeric NOT NULL CHECK (residual_rmse_s >= 0),
        track_temperature_min_c numeric,
        track_temperature_median_c numeric,
        track_temperature_max_c numeric,
        CONSTRAINT track_temperature_whole CHECK (
            num_nulls(track_temperature_min_c, track_temperature_median_c,
                      track_temperature_max_c) IN (0, 3)
        ),
        CONSTRAINT track_temperature_ordered CHECK (
            track_temperature_min_c <= track_temperature_median_c
            AND track_temperature_median_c <= track_temperature_max_c
        )
    )
    """,
    """
    CREATE TABLE calibration_compound (
        session_key integer NOT NULL REFERENCES calibration ON DELETE CASCADE,
        compound compound NOT NULL CHECK (compound IN ('SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE')),
        base_s numeric NOT NULL CHECK (base_s > 0),
        degradation_s_per_lap numeric NOT NULL,
        progress_s_per_lap numeric NOT NULL,
        residual_rmse_s numeric NOT NULL CHECK (residual_rmse_s >= 0),
        clean_laps integer NOT NULL CHECK (clean_laps > 0),
        min_tyre_age_laps integer NOT NULL CHECK (min_tyre_age_laps >= 0),
        max_tyre_age_laps integer NOT NULL,
        PRIMARY KEY (session_key, compound),
        CONSTRAINT tyre_ages_ordered CHECK (min_tyre_age_laps <= max_tyre_age_laps)
    )
    """,
    """
    CREATE TABLE calibration_driver (
        session_key integer NOT NULL REFERENCES calibration ON DELETE CASCADE,
        driver_number integer NOT NULL,
        pace_offset_s numeric NOT NULL,
        clean_laps integer NOT NULL CHECK (clean_laps > 0),
        PRIMARY KEY (session_key, driver_number),
        FOREIGN KEY (session_key, driver_number) REFERENCES driver_session ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE calibration_exclusion (
        session_key integer NOT NULL REFERENCES calibration_run ON DELETE CASCADE,
        reason exclusion_reason NOT NULL,
        laps integer NOT NULL CHECK (laps > 0),
        PRIMARY KEY (session_key, reason)
    )
    """,
)


def upgrade() -> None:
    for statement in (*TYPES, *TABLES):
        op.execute(statement)
