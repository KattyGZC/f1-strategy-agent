"""enable pgvector and add embedding column to race_summaries

Revision ID: a1b2c3d4e5f6
Revises: fd2cac4365b3
Create Date: 2026-02-26 19:44:46.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "fd2cac4365b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "race_summaries",
        sa.Column("embedding", Vector(1536), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("race_summaries", "embedding")
