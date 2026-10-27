"""The run table of the clean-model transform (ADR 0008).

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE transform_status AS ENUM ('pending', 'waiting_raw', 'succeeded', 'failed')"
    )
    op.execute("CREATE TYPE transform_error_kind AS ENUM ('transient', 'permanent')")
    op.execute(
        """
        CREATE TABLE transform_run (
            session_key integer PRIMARY KEY CHECK (session_key > 0),
            status transform_status NOT NULL,
            input_fingerprint text NOT NULL,
            transform_version text NOT NULL,
            attempts integer NOT NULL CHECK (attempts >= 0),
            error_kind transform_error_kind,
            error_message text,
            loaded_fingerprint text,
            loaded_version text,
            loaded_output_hash text,
            loaded_at timestamptz,
            updated_at timestamptz NOT NULL,
            CONSTRAINT failed_has_error CHECK (
                (status = 'failed') = (error_kind IS NOT NULL)
                AND (error_kind IS NULL) = (error_message IS NULL)
            ),
            CONSTRAINT loaded_is_whole CHECK (
                num_nulls(loaded_fingerprint, loaded_version, loaded_output_hash, loaded_at)
                IN (0, 4)
            ),
            CONSTRAINT succeeded_is_loaded CHECK (
                status <> 'succeeded'
                OR (
                    loaded_fingerprint IS NOT DISTINCT FROM input_fingerprint
                    AND loaded_version IS NOT DISTINCT FROM transform_version
                )
            )
        )
        """
    )
    op.execute("CREATE INDEX transform_run_status ON transform_run (status)")
