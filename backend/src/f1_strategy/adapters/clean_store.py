"""The clean model in PostgreSQL: the run table and the replace of a session (ADR 0008)."""

from collections.abc import AsyncIterator, Collection
from contextlib import asynccontextmanager
from dataclasses import astuple
from datetime import datetime

from psycopg import AsyncConnection, OperationalError, sql
from psycopg.rows import TupleRow
from psycopg_pool import AsyncConnectionPool

from f1_strategy.application.transform import (
    ErrorKind,
    Load,
    RunState,
    RunStatus,
    TransientError,
    Version,
)
from f1_strategy.domain.clean import CleanRecord, column_names

type Pool = AsyncConnectionPool[AsyncConnection[TupleRow]]

RUN_COLUMNS = (
    "status, input_fingerprint, transform_version, error_kind, loaded_fingerprint, loaded_version"
)


def connection_pool(postgres_uri: str, max_size: int, connect_timeout_s: int) -> Pool:
    """A closed pool sized for the workers; open it with `async with`."""
    return AsyncConnectionPool(
        postgres_uri,
        min_size=1,
        max_size=max_size,
        timeout=connect_timeout_s,
        kwargs={"connect_timeout": connect_timeout_s},
        open=False,
    )


class PostgresClaim:
    def __init__(self, connection: AsyncConnection[TupleRow], state: RunState) -> None:
        self._connection = connection
        self._state = state

    @property
    def state(self) -> RunState:
        return self._state

    async def replace(self, load: Load) -> None:
        clean = load.clean
        meeting = clean.meeting
        columns = column_names(type(meeting))
        await self._connection.execute(
            sql.SQL(
                "INSERT INTO meeting ({columns}) VALUES ({values}) "
                "ON CONFLICT (meeting_key) DO UPDATE SET ({columns}) = ({excluded})"
            ).format(
                columns=_identifiers(columns),
                values=sql.SQL(", ").join(sql.Placeholder() * len(columns)),
                excluded=sql.SQL(", ").join(
                    sql.SQL("EXCLUDED.{}").format(sql.Identifier(column)) for column in columns
                ),
            ),
            astuple(meeting),
        )
        session_key = clean.session.session_key
        # Every row of the session cascades from here (migration 0002).
        await self._connection.execute("DELETE FROM session WHERE session_key = %s", [session_key])
        await self._copy("session", (clean.session,))
        for table, rows in clean.tables():
            await self._copy(table, rows)
        await self._connection.execute(
            """
            UPDATE transform_run SET
                status = 'succeeded',
                input_fingerprint = %(fingerprint)s,
                transform_version = %(version)s,
                attempts = 0,
                error_kind = NULL,
                error_message = NULL,
                loaded_fingerprint = %(fingerprint)s,
                loaded_version = %(version)s,
                loaded_output_hash = %(output_hash)s,
                loaded_at = %(loaded_at)s,
                updated_at = %(loaded_at)s
            WHERE session_key = %(session_key)s
            """,
            {
                "fingerprint": load.version.input_fingerprint,
                "version": load.version.transform_version,
                "output_hash": load.output_hash,
                "loaded_at": load.loaded_at,
                "session_key": session_key,
            },
        )

    async def _copy(self, table: str, rows: tuple[CleanRecord, ...]) -> None:
        if not rows:
            return
        columns = column_names(type(rows[0]))
        statement = sql.SQL("COPY {table} ({columns}) FROM STDIN").format(
            table=sql.Identifier(table), columns=_identifiers(columns)
        )
        async with self._connection.cursor().copy(statement) as copy:
            for row in rows:
                await copy.write_row(astuple(row))


class PostgresCleanStore:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def runs(self, session_keys: Collection[int]) -> dict[int, RunState]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                f"SELECT session_key, {RUN_COLUMNS} FROM transform_run "  # noqa: S608
                "WHERE session_key = ANY(%s)",
                [list(session_keys)],
            )
            return {row[0]: _state(row[1:]) for row in await cursor.fetchall()}

    @asynccontextmanager
    async def claim(
        self, session_key: int, version: Version, now: datetime
    ) -> AsyncIterator[PostgresClaim | None]:
        """Hold the session's run row for the block: its lock lasts as long as the transaction,
        so a worker that dies releases it and leaves the session pending."""
        try:
            async with self._pool.connection() as connection:
                await connection.execute(
                    """
                    INSERT INTO transform_run
                        (session_key, status, input_fingerprint, transform_version, attempts,
                         updated_at)
                    VALUES (%s, 'pending', %s, %s, 0, %s)
                    ON CONFLICT (session_key) DO NOTHING
                    """,
                    [session_key, version.input_fingerprint, version.transform_version, now],
                )
                await connection.commit()
                async with connection.transaction():
                    cursor = await connection.execute(
                        f"SELECT {RUN_COLUMNS} FROM transform_run "  # noqa: S608
                        "WHERE session_key = %s FOR UPDATE SKIP LOCKED",
                        [session_key],
                    )
                    row = await cursor.fetchone()
                    yield None if row is None else PostgresClaim(connection, _state(row))
        except OperationalError as error:
            # Lost connections, serialization failures and deadlocks are OperationalErrors;
            # constraint violations are not, and fail the session for good.
            raise TransientError(f"{type(error).__name__}: {error}") from error

    async def record_waiting(self, session_key: int, version: Version, now: datetime) -> None:
        """Mark the session as waiting for raw data. updated_at keeps the moment it started
        waiting, so an alert can tell how long it has waited."""
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO transform_run AS run
                    (session_key, status, input_fingerprint, transform_version, attempts,
                     updated_at)
                VALUES (%(session_key)s, 'waiting_raw', %(fingerprint)s, %(version)s, 0, %(now)s)
                ON CONFLICT (session_key) DO UPDATE SET
                    status = 'waiting_raw',
                    input_fingerprint = EXCLUDED.input_fingerprint,
                    transform_version = EXCLUDED.transform_version,
                    error_kind = NULL,
                    error_message = NULL,
                    updated_at = CASE WHEN run.status = 'waiting_raw'
                        THEN run.updated_at ELSE EXCLUDED.updated_at END
                """,
                {
                    "session_key": session_key,
                    "fingerprint": version.input_fingerprint,
                    "version": version.transform_version,
                    "now": now,
                },
            )

    async def record_failure(
        self, session_key: int, version: Version, kind: ErrorKind, message: str, now: datetime
    ) -> None:
        """Mark the session as failed; its last load, if any, stays and stays readable."""
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO transform_run AS run
                    (session_key, status, input_fingerprint, transform_version, attempts,
                     error_kind, error_message, updated_at)
                VALUES (%(session_key)s, 'failed', %(fingerprint)s, %(version)s, 1, %(kind)s,
                        %(message)s, %(now)s)
                ON CONFLICT (session_key) DO UPDATE SET
                    status = 'failed',
                    input_fingerprint = EXCLUDED.input_fingerprint,
                    transform_version = EXCLUDED.transform_version,
                    attempts = run.attempts + 1,
                    error_kind = EXCLUDED.error_kind,
                    error_message = EXCLUDED.error_message,
                    updated_at = EXCLUDED.updated_at
                """,
                {
                    "session_key": session_key,
                    "fingerprint": version.input_fingerprint,
                    "version": version.transform_version,
                    "kind": kind,
                    "message": message,
                    "now": now,
                },
            )


def _state(row: tuple[object, ...]) -> RunState:
    status, fingerprint, version, error_kind, loaded_fingerprint, loaded_version = row
    loaded = (
        None
        if loaded_fingerprint is None
        else Version(str(loaded_fingerprint), str(loaded_version))
    )
    return RunState(
        status=RunStatus(str(status)),
        current=Version(str(fingerprint), str(version)),
        error_kind=None if error_kind is None else ErrorKind(str(error_kind)),
        loaded=loaded,
    )


def _identifiers(columns: tuple[str, ...]) -> sql.Composed:
    return sql.SQL(", ").join(sql.Identifier(column) for column in columns)
