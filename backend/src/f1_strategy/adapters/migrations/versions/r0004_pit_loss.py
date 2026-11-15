"""The pit loss of each calibrated race, measured on its own stops (ADR 0015).

Both tables cascade from the race's calibration, so a new calibration replaces them with it.
Calibrations of version 1 have no pit loss; the next calibrate run replaces them.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"

TYPES = (
    """CREATE TYPE pit_stop_exclusion_reason AS ENUM (
        'reference_is_first_lap', 'missing_lap', 'untimed_lap', 'next_to_another_stop',
        'neutralised'
    )""",
)

TABLES = (
    """
    CREATE TABLE calibration_pit_loss (
        session_key integer PRIMARY KEY REFERENCES calibration ON DELETE CASCADE,
        pit_loss_s numeric NOT NULL CHECK (pit_loss_s > 0),
        stops integer NOT NULL CHECK (stops > 0)
    )
    """,
    """
    CREATE TABLE calibration_pit_stop_exclusion (
        session_key integer NOT NULL REFERENCES calibration ON DELETE CASCADE,
        reason pit_stop_exclusion_reason NOT NULL,
        stops integer NOT NULL CHECK (stops > 0),
        PRIMARY KEY (session_key, reason)
    )
    """,
)


def upgrade() -> None:
    for statement in (*TYPES, *TABLES):
        op.execute(statement)
