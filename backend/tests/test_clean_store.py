from collections.abc import AsyncIterator, Sequence
from dataclasses import astuple, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from psycopg import errors

from f1_strategy.adapters.clean_store import (
    Pool,
    PostgresCleanStore,
    PostgresReplayRows,
    PostgresSessionCatalog,
    connection_pool,
)
from f1_strategy.adapters.migrate import upgrade
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
    CleanSession,
    Compound,
    Flag,
    FlagScope,
    RaceControlCategory,
    clean_session,
    column_names,
    content_hash,
)
from f1_strategy.domain.replay import timeline
from tests.postgres import CONNECT_TIMEOUT_S, fresh_database
from tests.samples import QUALIFYING, RACE, sample

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
VERSION = Version("input-1", "1")
RACE_KEY = int(RACE)
QUALIFYING_KEY = int(QUALIFYING)


@pytest.fixture
def postgres_uri(postgres_server_uri: str) -> str:
    uri = fresh_database(postgres_server_uri)
    upgrade(uri, CONNECT_TIMEOUT_S)
    return uri


@pytest.fixture
async def store(postgres_uri: str) -> AsyncIterator[PostgresCleanStore]:
    pool: Pool = connection_pool(postgres_uri, max_size=3, connect_timeout_s=CONNECT_TIMEOUT_S)
    async with pool:
        yield PostgresCleanStore(pool)


def clean(session_key: str) -> CleanSession:
    return clean_session(sample(session_key).raw())


def load(session: CleanSession, version: Version = VERSION) -> Load:
    return Load(session, version, content_hash(session), NOW)


async def load_session(
    store: PostgresCleanStore, session: CleanSession, version: Version = VERSION
) -> None:
    async with store.claim(session.session.session_key, version, NOW) as claim:
        assert claim is not None
        await claim.replace(load(session, version))


def tables(session: CleanSession) -> list[tuple[str, Sequence[CleanRecord]]]:
    return [("meeting", (session.meeting,)), ("session", (session.session,)), *session.tables()]


def stored(postgres_uri: str, session: CleanSession) -> dict[str, set[tuple[object, ...]]]:
    """Every row of the session's tables, read back as tuples in the dataclasses' field order."""
    read: dict[str, set[tuple[object, ...]]] = {}
    with psycopg.connect(postgres_uri, connect_timeout=CONNECT_TIMEOUT_S) as connection:
        for table, rows in tables(session):
            if not rows:
                continue
            columns = ", ".join(column_names(type(rows[0])))
            key = "meeting_key" if table == "meeting" else "session_key"
            value = (
                session.meeting.meeting_key if table == "meeting" else session.session.session_key
            )
            cursor = connection.execute(
                f"SELECT {columns} FROM {table} WHERE {key} = %s",  # noqa: S608 - names come from the test, values are bound
                [value],
            )
            read[table] = set(cursor.fetchall())
    return read


def expected(session: CleanSession) -> dict[str, set[tuple[object, ...]]]:
    return {table: {astuple(row) for row in rows} for table, rows in tables(session) if rows}


def run_row(postgres_uri: str, session_key: int) -> dict[str, object]:
    with psycopg.connect(
        postgres_uri, connect_timeout=CONNECT_TIMEOUT_S, row_factory=psycopg.rows.dict_row
    ) as connection:
        row = connection.execute(
            "SELECT * FROM transform_run WHERE session_key = %s", [session_key]
        ).fetchone()
    assert row is not None
    return row


@pytest.mark.anyio
async def test_a_load_writes_every_row_and_reads_back_equal(
    store: PostgresCleanStore, postgres_uri: str
) -> None:
    race = clean(RACE)

    await load_session(store, race)

    assert stored(postgres_uri, race) == expected(race)
    run = run_row(postgres_uri, RACE_KEY)
    assert (run["status"], run["loaded_output_hash"], run["loaded_at"]) == (
        "succeeded",
        content_hash(race),
        NOW,
    )


@pytest.mark.anyio
async def test_numbers_and_instants_survive_the_round_trip_exactly(
    store: PostgresCleanStore, postgres_uri: str
) -> None:
    race = clean(RACE)
    lap = replace(race.laps[0], lap_duration=Decimal("91.234"))
    race = replace(race, laps=(lap, *race.laps[1:]))

    await load_session(store, race)

    with psycopg.connect(postgres_uri, connect_timeout=CONNECT_TIMEOUT_S) as connection:
        row = connection.execute(
            "SELECT lap_duration, date_start FROM lap "
            "WHERE session_key = %s AND driver_number = %s AND lap_number = %s",
            [lap.session_key, lap.driver_number, lap.lap_number],
        ).fetchone()
    assert row == (Decimal("91.234"), lap.date_start)


@pytest.mark.anyio
async def test_loading_a_session_again_replaces_its_rows(
    store: PostgresCleanStore, postgres_uri: str
) -> None:
    race = clean(RACE)
    await load_session(store, race)
    fewer = replace(race, laps=race.laps[:2], weather=())

    await load_session(store, fewer, Version("input-2", "1"))

    assert stored(postgres_uri, fewer) == expected(fewer)
    assert run_row(postgres_uri, RACE_KEY)["loaded_fingerprint"] == "input-2"


@pytest.mark.anyio
async def test_loading_one_session_leaves_the_others_alone(
    store: PostgresCleanStore, postgres_uri: str
) -> None:
    race, qualifying = clean(RACE), clean(QUALIFYING)
    await load_session(store, qualifying)

    await load_session(store, race)
    await load_session(store, race)

    assert stored(postgres_uri, qualifying) == expected(qualifying)


@pytest.mark.anyio
async def test_a_session_held_by_one_claim_is_skipped_by_another(
    store: PostgresCleanStore,
) -> None:
    async with (
        store.claim(RACE_KEY, VERSION, NOW) as first,
        store.claim(RACE_KEY, VERSION, NOW) as second,
    ):
        assert first is not None
        assert second is None


@pytest.mark.anyio
async def test_a_failure_inside_a_claim_rolls_the_whole_load_back(
    store: PostgresCleanStore, postgres_uri: str
) -> None:
    race = clean(RACE)

    async def die_after_replace() -> None:
        async with store.claim(RACE_KEY, VERSION, NOW) as claim:
            assert claim is not None
            assert claim.state == RunState(RunStatus.PENDING, VERSION, None, None)
            await claim.replace(load(race))
            raise RuntimeError("worker died")

    with pytest.raises(RuntimeError, match="worker died"):
        await die_after_replace()

    assert not any(stored(postgres_uri, race).values())
    assert run_row(postgres_uri, RACE_KEY)["status"] == "pending"


@pytest.mark.anyio
async def test_a_row_the_schema_rejects_is_not_a_transient_error(
    store: PostgresCleanStore,
) -> None:
    race = clean(RACE)
    broken = replace(race, laps=(replace(race.laps[0], lap_duration=Decimal(0)),))

    with pytest.raises(errors.CheckViolation, match="lap_lap_duration_check"):
        await load_session(store, broken)


@pytest.mark.anyio
async def test_a_lost_connection_is_a_transient_error(store: PostgresCleanStore) -> None:
    async def lose_the_connection() -> None:
        async with store.claim(RACE_KEY, VERSION, NOW) as claim:
            assert claim is not None
            await claim._connection.execute("SELECT pg_terminate_backend(pg_backend_pid())")

    with pytest.raises(TransientError, match="AdminShutdown"):
        await lose_the_connection()


@pytest.mark.anyio
async def test_runs_reads_the_state_of_each_known_session(store: PostgresCleanStore) -> None:
    await load_session(store, clean(RACE))
    await store.record_waiting(QUALIFYING_KEY, VERSION, NOW)

    runs = await store.runs([RACE_KEY, QUALIFYING_KEY, 1])

    assert runs == {
        RACE_KEY: RunState(RunStatus.SUCCEEDED, VERSION, None, VERSION),
        QUALIFYING_KEY: RunState(RunStatus.WAITING_RAW, VERSION, None, None),
    }


@pytest.mark.anyio
async def test_waiting_keeps_the_moment_it_started(
    store: PostgresCleanStore, postgres_uri: str
) -> None:
    await store.record_waiting(RACE_KEY, VERSION, NOW)

    await store.record_waiting(RACE_KEY, Version("input-2", "1"), NOW + timedelta(hours=1))

    run = run_row(postgres_uri, RACE_KEY)
    assert (run["input_fingerprint"], run["updated_at"]) == ("input-2", NOW)


@pytest.mark.anyio
async def test_a_failure_counts_attempts_and_keeps_the_last_load(
    store: PostgresCleanStore, postgres_uri: str
) -> None:
    race = clean(RACE)
    await load_session(store, race)
    newer = Version("input-2", "1")

    await store.record_failure(RACE_KEY, newer, ErrorKind.TRANSIENT, "lost", NOW)
    await store.record_failure(RACE_KEY, newer, ErrorKind.PERMANENT, "bad lap", NOW)

    runs = await store.runs([RACE_KEY])
    run = run_row(postgres_uri, RACE_KEY)
    assert runs[RACE_KEY] == RunState(RunStatus.FAILED, newer, ErrorKind.PERMANENT, VERSION)
    assert (run["attempts"], run["error_message"]) == (2, "bad lap")
    assert stored(postgres_uri, race) == expected(race)


@pytest.mark.anyio
async def test_a_first_failure_creates_the_run(
    store: PostgresCleanStore, postgres_uri: str
) -> None:
    await store.record_failure(RACE_KEY, VERSION, ErrorKind.PERMANENT, "bad lap", NOW)

    run = run_row(postgres_uri, RACE_KEY)
    assert (run["status"], run["attempts"], run["loaded_fingerprint"]) == ("failed", 1, None)


@pytest.mark.anyio
async def test_a_load_after_a_failure_clears_the_error(
    store: PostgresCleanStore, postgres_uri: str
) -> None:
    await store.record_failure(RACE_KEY, VERSION, ErrorKind.TRANSIENT, "lost", NOW)

    await load_session(store, clean(RACE))

    run = run_row(postgres_uri, RACE_KEY)
    assert (run["status"], run["attempts"], run["error_kind"]) == ("succeeded", 0, None)


REPLAYED_TABLES = (
    "laps",
    "stints",
    "pits",
    "intervals",
    "positions",
    "race_control",
    "weather",
    "overtakes",
    "team_radio",
)


@pytest.mark.anyio
@pytest.mark.parametrize("key", [RACE, QUALIFYING])
async def test_a_loaded_session_reads_back_as_its_replayed_rows(
    store: PostgresCleanStore, postgres_uri: str, key: str
) -> None:
    session = clean(key)
    await load_session(store, clean(QUALIFYING if key == RACE else RACE))
    await load_session(store, session)
    pool: Pool = connection_pool(postgres_uri, max_size=1, connect_timeout_s=CONNECT_TIMEOUT_S)
    async with pool:
        rows = await PostgresReplayRows(pool).timeline_rows(session.session.session_key)

    assert rows is not None
    for table in REPLAYED_TABLES:
        assert getattr(rows, table) == getattr(session, table), table
    assert timeline(rows) == timeline(session)


@pytest.mark.anyio
async def test_closed_sets_read_back_as_their_enums(
    store: PostgresCleanStore, postgres_uri: str
) -> None:
    session = clean(RACE)
    await load_session(store, session)
    pool: Pool = connection_pool(postgres_uri, max_size=1, connect_timeout_s=CONNECT_TIMEOUT_S)
    async with pool:
        rows = await PostgresReplayRows(pool).timeline_rows(RACE_KEY)

    assert rows is not None
    assert {type(stint.compound) for stint in rows.stints} == {Compound}
    assert {type(row.category) for row in rows.race_control} == {RaceControlCategory}
    flagged = [row for row in rows.race_control if row.flag is not None]
    assert flagged
    assert {(type(row.flag), type(row.scope)) for row in flagged} == {(Flag, FlagScope)}


@pytest.mark.anyio
async def test_a_session_is_replayable_only_once_loaded(
    store: PostgresCleanStore, postgres_uri: str
) -> None:
    pool: Pool = connection_pool(postgres_uri, max_size=1, connect_timeout_s=CONNECT_TIMEOUT_S)
    async with pool:
        replay_rows = PostgresReplayRows(pool)
        before = (await replay_rows.is_loaded(RACE_KEY), await replay_rows.timeline_rows(RACE_KEY))
        await load_session(store, clean(RACE))
        after = await replay_rows.is_loaded(RACE_KEY)

    assert before == (False, None)
    assert after is True


@pytest.mark.anyio
async def test_a_database_missing_an_enum_type_fails_the_read_by_name(
    store: PostgresCleanStore, postgres_uri: str
) -> None:
    await load_session(store, clean(RACE))
    with psycopg.connect(postgres_uri, autocommit=True) as connection:
        connection.execute("ALTER TYPE flag_scope RENAME TO renamed_scope")
    pool: Pool = connection_pool(postgres_uri, max_size=1, connect_timeout_s=CONNECT_TIMEOUT_S)

    async with pool:
        with pytest.raises(LookupError, match="enum type flag_scope is not in the database"):
            await PostgresReplayRows(pool).timeline_rows(RACE_KEY)


def loaded(session: CleanSession) -> LoadedSession:
    return LoadedSession(
        session_key=session.session.session_key,
        session_type=session.session.session_type,
        session_name=session.session.session_name,
        date_start=session.session.date_start,
        meeting_key=session.meeting.meeting_key,
        year=session.meeting.year,
        meeting_name=session.meeting.meeting_name,
        circuit_short_name=session.meeting.circuit_short_name,
        country_name=session.meeting.country_name,
    )


@pytest.fixture
async def catalog(postgres_uri: str) -> AsyncIterator[PostgresSessionCatalog]:
    pool: Pool = connection_pool(postgres_uri, max_size=1, connect_timeout_s=CONNECT_TIMEOUT_S)
    async with pool:
        yield PostgresSessionCatalog(pool)


@pytest.mark.anyio
async def test_the_catalog_lists_every_loaded_session_latest_first(
    store: PostgresCleanStore, catalog: PostgresSessionCatalog
) -> None:
    empty = await catalog.sessions()
    await load_session(store, clean(RACE))
    await load_session(store, clean(QUALIFYING))

    assert empty == ()
    assert await catalog.sessions() == (loaded(clean(RACE)), loaded(clean(QUALIFYING)))


@pytest.mark.anyio
async def test_sessions_that_start_together_list_the_higher_key_first(
    store: PostgresCleanStore, catalog: PostgresSessionCatalog, postgres_uri: str
) -> None:
    qualifying = clean(QUALIFYING)
    await load_session(store, qualifying)
    await load_session(store, clean(RACE))
    with psycopg.connect(postgres_uri, autocommit=True) as connection:
        connection.execute(
            "UPDATE session SET date_start = %s WHERE session_key = %s",
            [qualifying.session.date_start, RACE_KEY],
        )

    assert [session.session_key for session in await catalog.sessions()] == [
        RACE_KEY,
        QUALIFYING_KEY,
    ]


@pytest.mark.anyio
async def test_an_entry_holds_its_session_and_its_drivers_by_number(
    store: PostgresCleanStore, catalog: PostgresSessionCatalog
) -> None:
    race = clean(RACE)
    await load_session(store, race)
    await load_session(store, clean(QUALIFYING))
    drivers = tuple(
        SessionDriver(
            driver_number=driver.driver_number,
            name_acronym=driver.name_acronym,
            full_name=driver.full_name,
            team_name=driver.team_name,
            team_colour=driver.team_colour,
        )
        for driver in sorted(race.drivers, key=lambda driver: driver.driver_number)
    )

    assert await catalog.entry(RACE_KEY) == SessionEntry(loaded(race), drivers, 4)


@pytest.mark.anyio
async def test_an_entry_without_laps_has_no_last_lap(
    store: PostgresCleanStore, catalog: PostgresSessionCatalog
) -> None:
    race = replace(clean(RACE), laps=())
    await load_session(store, race)

    entry = await catalog.entry(RACE_KEY)

    assert entry is not None
    assert entry.last_lap_number is None


@pytest.mark.anyio
async def test_a_session_not_loaded_has_no_entry(
    store: PostgresCleanStore, catalog: PostgresSessionCatalog
) -> None:
    await load_session(store, clean(QUALIFYING))

    assert await catalog.entry(RACE_KEY) is None
