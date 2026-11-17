"""The rain readings of each calibrated race, for the simulator to name rain it does not model
(ADR 0017).

Calibrations of version 2 cannot have the count without the weather rows they were fitted
from, and a calibration is derived whole from the clean model: they are deleted with their
runs, so the column holds a fact from the start, and the next calibrate run rebuilds them.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute("DELETE FROM calibration_run")
    op.execute(
        "ALTER TABLE calibration ADD COLUMN rain_readings integer NOT NULL"
        " CHECK (rain_readings >= 0)"
    )
