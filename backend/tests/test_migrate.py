from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg.errors import CheckViolation

from f1_strategy.adapters.migrate import main, upgrade
from tests.postgres import CONNECT_TIMEOUT_S, fresh_database

HEAD = "0002"
NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
LOADED = {
    "loaded_fingerprint": "in-1",
    "loaded_version": "v1",
    "loaded_output_hash": "out-1",
    "loaded_at": NOW,
}
NOT_LOADED = dict.fromkeys(LOADED)


@pytest.fixture
def postgres_uri(postgres_server_uri: str) -> str:
    return fresh_database(postgres_server_uri)


def schema_version(postgres_uri: str) -> list[str]:
    with psycopg.connect(postgres_uri, connect_timeout=CONNECT_TIMEOUT_S) as connection:
        rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    return [row[0] for row in rows]


def insert_run(postgres_uri: str, **overrides: object) -> None:
    row: dict[str, object] = {
        "session_key": 9472,
        "status": "pending",
        "input_fingerprint": "in-1",
        "transform_version": "v1",
        "attempts": 0,
        "error_kind": None,
        "error_message": None,
        **NOT_LOADED,
        "updated_at": NOW,
        **overrides,
    }
    columns = ", ".join(row)
    values = ", ".join(f"%({column})s" for column in row)
    with psycopg.connect(postgres_uri, connect_timeout=CONNECT_TIMEOUT_S) as connection:
        connection.execute(f"INSERT INTO transform_run ({columns}) VALUES ({values})", row)  # noqa: S608


def test_upgrade_brings_an_empty_database_to_the_latest_migration(postgres_uri: str) -> None:
    upgrade(postgres_uri, CONNECT_TIMEOUT_S)

    assert schema_version(postgres_uri) == [HEAD]


def test_a_second_upgrade_changes_nothing(postgres_uri: str) -> None:
    upgrade(postgres_uri, CONNECT_TIMEOUT_S)
    insert_run(postgres_uri)

    upgrade(postgres_uri, CONNECT_TIMEOUT_S)

    assert schema_version(postgres_uri) == [HEAD]
    with psycopg.connect(postgres_uri, connect_timeout=CONNECT_TIMEOUT_S) as connection:
        assert connection.execute("SELECT count(*) FROM transform_run").fetchone() == (1,)


def test_concurrent_upgrades_from_two_processes_both_succeed(postgres_uri: str) -> None:
    with ProcessPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(upgrade, postgres_uri, CONNECT_TIMEOUT_S) for _ in range(2)]:
            future.result()

    assert schema_version(postgres_uri) == [HEAD]


def test_main_migrates_the_database_named_by_the_environment(
    postgres_uri: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POSTGRES_URI", postgres_uri)
    monkeypatch.setenv("POSTGRES_CONNECT_TIMEOUT_S", str(CONNECT_TIMEOUT_S))

    assert main() == 0
    assert schema_version(postgres_uri) == [HEAD]


@pytest.mark.parametrize(
    "row",
    [
        pytest.param({"status": "succeeded", **LOADED}, id="succeeded"),
        pytest.param(
            {"status": "failed", "error_kind": "permanent", "error_message": "unknown compound"},
            id="failed",
        ),
        pytest.param({"status": "waiting_raw"}, id="waiting raw"),
        pytest.param(
            {"status": "failed", "error_kind": "transient", "error_message": "lost", **LOADED},
            id="failed after an earlier load",
        ),
    ],
)
def test_the_run_table_accepts_consistent_rows(postgres_uri: str, row: dict[str, object]) -> None:
    upgrade(postgres_uri, CONNECT_TIMEOUT_S)

    insert_run(postgres_uri, **row)


@pytest.mark.parametrize(
    ("row", "constraint"),
    [
        pytest.param({"status": "failed"}, "failed_has_error", id="failed without an error"),
        pytest.param(
            {"error_kind": "transient", "error_message": "lost"},
            "failed_has_error",
            id="error on a run that did not fail",
        ),
        pytest.param(
            {"status": "failed", "error_kind": "permanent"},
            "failed_has_error",
            id="error without a message",
        ),
        pytest.param(
            {"loaded_fingerprint": "in-1", "loaded_version": "v1"},
            "loaded_is_whole",
            id="half a load",
        ),
        pytest.param({"status": "succeeded"}, "succeeded_is_loaded", id="succeeded, never loaded"),
        pytest.param(
            {"status": "succeeded", **LOADED, "loaded_fingerprint": "in-0"},
            "succeeded_is_loaded",
            id="succeeded with another input",
        ),
        pytest.param(
            {"status": "succeeded", **LOADED, "loaded_version": "v0"},
            "succeeded_is_loaded",
            id="succeeded with another version",
        ),
        pytest.param({"attempts": -1}, "transform_run_attempts_check", id="negative attempts"),
        pytest.param({"session_key": 0}, "transform_run_session_key_check", id="session key 0"),
    ],
)
def test_the_run_table_rejects_inconsistent_rows(
    postgres_uri: str, row: dict[str, object], constraint: str
) -> None:
    upgrade(postgres_uri, CONNECT_TIMEOUT_S)

    with pytest.raises(CheckViolation) as rejected:
        insert_run(postgres_uri, **row)

    assert rejected.value.diag.constraint_name == constraint
