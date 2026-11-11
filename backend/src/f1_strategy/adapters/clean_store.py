"""The clean model in PostgreSQL: the run table and the replace of a session (ADR 0008), and
the read of a session's rows for its replay (ADR 0009), and the catalog of loaded sessions."""

from collections.abc import AsyncIterator, Collection
from contextlib import asynccontextmanager
from dataclasses import astuple, dataclass
from datetime import datetime
from enum import StrEnum

from psycopg import AsyncConnection, OperationalError, sql
from psycopg.rows import TupleRow, class_row
from psycopg.types.enum import EnumInfo, register_enum
from psycopg_pool import AsyncConnectionPool

from f1_strategy.application.sessions import LoadedSession, SessionDriver, SessionEntry
from f1_strategy.application.transform import (
    ErrorKind,
    Load,
    RunState,
    RunStatus,
    TransientError,
    Version,
)
from f1_strategy.domain.clean import (
    CleanRecord,
    Compound,
    Flag,
    FlagScope,
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
    column_names,
)
from f1_strategy.domain.openf1 import SessionName, SessionType

type Pool = AsyncConnectionPool[AsyncConnection[TupleRow]]

type EnumTypes = tuple[tuple[str, type[StrEnum]], ...]

# The database enum type of each closed set the replayed tables hold (migration 0002).
REPLAYED_ENUM_TYPES: EnumTypes = (
    ("compound", Compound),
    ("race_control_category", RaceControlCategory),
    ("flag", Flag),
    ("flag_scope", FlagScope),
)
CATALOG_ENUM_TYPES: EnumTypes = (("session_type", SessionType), ("session_name", SessionName))

SESSION_SELECT = """
    SELECT s.session_key, s.session_type, s.session_name, s.date_start, m.meeting_key, m.year,
        m.meeting_name, m.circuit_short_name, m.country_name
    FROM session s JOIN meeting m USING (meeting_key)
"""
SESSIONS_QUERY = SESSION_SELECT + "ORDER BY s.date_start DESC, s.session_key DESC"
SESSION_QUERY = SESSION_SELECT + "WHERE s.session_key = %s"
DRIVERS_QUERY = """
    SELECT driver_number, name_acronym, full_name, team_name, team_colour
    FROM driver_session WHERE session_key = %s ORDER BY driver_number
"""
LAST_LAP_QUERY = "SELECT max(lap_number) FROM lap WHERE session_key = %s"

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
                f"SELECT session_key, {RUN_COLUMNS} FROM transform_run "  # noqa: S608 - RUN_COLUMNS is a constant
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
                        f"SELECT {RUN_COLUMNS} FROM transform_run "  # noqa: S608 - RUN_COLUMNS is a constant
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


@dataclass(frozen=True)
class SessionRows:
    laps: tuple[Lap, ...]
    stints: tuple[Stint, ...]
    pits: tuple[Pit, ...]
    intervals: tuple[Interval, ...]
    positions: tuple[Position, ...]
    race_control: tuple[RaceControl, ...]
    weather: tuple[Weather, ...]
    overtakes: tuple[Overtake, ...]
    team_radio: tuple[TeamRadio, ...]


class PostgresReplayRows:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def is_loaded(self, session_key: int) -> bool:
        async with self._pool.connection() as connection:
            return await _is_loaded(connection, session_key)

    async def timeline_rows(self, session_key: int) -> SessionRows | None:
        """The session's replayed rows, all from one snapshot: a load that commits while they
        are read is seen whole or not at all."""
        async with self._pool.connection() as connection, connection.transaction():
            await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            if not await _is_loaded(connection, session_key):
                return None
            await _register_enums(connection, REPLAYED_ENUM_TYPES)
            read = _SessionReader(connection, session_key)
            return SessionRows(
                laps=await read(Lap, "lap", ("driver_number", "lap_number")),
                stints=await read(Stint, "stint", ("driver_number", "stint_number")),
                pits=await read(Pit, "pit", ("driver_number", "lap_number")),
                intervals=await read(Interval, "interval", ("driver_number", "date")),
                positions=await read(Position, "position", ("driver_number", "date")),
                race_control=await read(RaceControl, "race_control", ("seq",)),
                weather=await read(Weather, "weather", ("date",)),
                overtakes=await read(
                    Overtake,
                    "overtake",
                    ("date", "overtaking_driver_number", "overtaken_driver_number"),
                ),
                team_radio=await read(TeamRadio, "team_radio", ("driver_number", "date")),
            )


class PostgresSessionCatalog:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def sessions(self) -> tuple[LoadedSession, ...]:
        async with self._pool.connection() as connection:
            await _register_enums(connection, CATALOG_ENUM_TYPES)
            async with connection.cursor(row_factory=class_row(LoadedSession)) as cursor:
                await cursor.execute(SESSIONS_QUERY)
                return tuple(await cursor.fetchall())

    async def entry(self, session_key: int) -> SessionEntry | None:
        """The session and its drivers from one snapshot, as `timeline_rows` reads them."""
        async with self._pool.connection() as connection, connection.transaction():
            await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            await _register_enums(connection, CATALOG_ENUM_TYPES)
            async with connection.cursor(row_factory=class_row(LoadedSession)) as cursor:
                await cursor.execute(SESSION_QUERY, [session_key])
                session = await cursor.fetchone()
            if session is None:
                return None
            async with connection.cursor(row_factory=class_row(SessionDriver)) as cursor:
                await cursor.execute(DRIVERS_QUERY, [session_key])
                drivers = tuple(await cursor.fetchall())
            return SessionEntry(session, drivers, await _last_lap_number(connection, session_key))


async def _last_lap_number(connection: AsyncConnection[TupleRow], session_key: int) -> int | None:
    cursor = await connection.execute(LAST_LAP_QUERY, [session_key])
    row = await cursor.fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


async def _is_loaded(connection: AsyncConnection[TupleRow], session_key: int) -> bool:
    cursor = await connection.execute(
        "SELECT EXISTS (SELECT 1 FROM session WHERE session_key = %s)", [session_key]
    )
    row = await cursor.fetchone()
    return row is not None and row[0] is True


class _SessionReader:
    def __init__(self, connection: AsyncConnection[TupleRow], session_key: int) -> None:
        self._connection = connection
        self._session_key = session_key

    async def __call__[T: CleanRecord](
        self, row_type: type[T], table: str, order_by: tuple[str, ...]
    ) -> tuple[T, ...]:
        statement = sql.SQL("SELECT {columns} FROM {table} WHERE session_key = %s ORDER BY {key}")
        query = statement.format(
            columns=_identifiers(column_names(row_type)),
            table=sql.Identifier(table),
            key=_identifiers(order_by),
        )
        async with self._connection.cursor(row_factory=class_row(row_type)) as cursor:
            await cursor.execute(query, [self._session_key])
            return tuple(await cursor.fetchall())


async def _register_enums(connection: AsyncConnection[TupleRow], enum_types: EnumTypes) -> None:
    for type_name, enum in enum_types:
        info = await EnumInfo.fetch(connection, type_name)
        if info is None:
            raise LookupError(f"enum type {type_name} is not in the database; run the migrations")
        register_enum(info, connection, enum, mapping={member: member.value for member in enum})


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
