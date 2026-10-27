from datetime import UTC, datetime, timedelta
from urllib.parse import unquote
from uuid import uuid4

import httpx2
import pytest
from pydantic import ValidationError
from pymongo import MongoClient

from f1_strategy.adapters.cli import main
from f1_strategy.adapters.raw_store import COLLECTION
from tests.factories import DRIVERS, RACE_END, SEASON_2024, SEASON_2024_SETTLED, session_row

SETTINGS = {
    "OPENF1_BASE_URL": "https://openf1.test/v1",
    "OPENF1_REQUESTS_PER_SECOND": "1000",
    "OPENF1_REQUESTS_PER_MINUTE": "1000",
    "OPENF1_MAX_CONCURRENCY": "3",
    "OPENF1_MAX_ATTEMPTS": "1",
    "OPENF1_BACKOFF_BASE_S": "0.01",
    "OPENF1_TIMEOUT_S": "5",
    "SESSION_SETTLE_H": "6",
    "TELEMETRY_WINDOW_MIN": "30",
}
NO_RESULTS = {"detail": "No results found."}
SEASON_REQUESTS = 2 + 11 + 10
TELEMETRY_REQUESTS = 2 + 2 * 2 * 4


def openf1(request: httpx2.Request) -> httpx2.Response:
    endpoint = request.url.path.removeprefix("/v1/")
    params = dict(request.url.params)
    if endpoint == "sessions" and params.get("year") == "2024":
        return httpx2.Response(200, json=SEASON_2024)
    if endpoint == "sessions" and params == {"session_key": "9472"}:
        return httpx2.Response(200, json=[session_row(9472, "Race")])
    if endpoint == "drivers":
        return httpx2.Response(200, json=DRIVERS)
    if endpoint == "laps" and params["session_key"] == "9468":
        return httpx2.Response(422, json={"detail": "too much data"})
    return httpx2.Response(404, json=NO_RESULTS)


def run(argv: list[str], clock: datetime = SEASON_2024_SETTLED) -> int:
    return main(argv, transport=httpx2.MockTransport(openf1), clock=lambda: clock)


@pytest.fixture
def database(mongo_uri: str, monkeypatch: pytest.MonkeyPatch) -> str:
    name = f"cli_{uuid4().hex}"
    for variable, value in {**SETTINGS, "MONGO_URI": mongo_uri, "MONGO_DATABASE": name}.items():
        monkeypatch.setenv(variable, value)
    return name


def stored_keys(mongo_uri: str, database: str) -> set[str]:
    with MongoClient[dict[str, object]](mongo_uri) as client:
        return {str(document["_id"]) for document in client[database][COLLECTION].find({}, {})}


def test_season_ingests_the_chosen_session_type_then_resumes_with_nothing_to_fetch(
    mongo_uri: str, database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_codes = [
        run(["season", "--year", "2024", "--session-type", "Race"]),
        run(["season", "--year", "2024", "--session-type", "Race"]),
    ]

    assert exit_codes == [0, 0]
    assert capsys.readouterr().out.splitlines() == [
        "ingested 1 sessions: 13 requests, 13 fetched, 0 already stored",
        "ingested 1 sessions: 13 requests, 0 fetched, 13 already stored",
    ]
    assert len(stored_keys(mongo_uri, database)) == 2 + 11


def test_season_fails_with_one_line_naming_the_request_and_keeps_what_was_stored(
    mongo_uri: str, database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = run(["season", "--year", "2024"])

    output = capsys.readouterr()
    assert exit_code == 1
    assert output.out == ""
    assert output.err == (
        'ingestion failed: GET /laps?session_key=9468 -> 422 {"detail":"too much data"}\n'
    )
    stored = stored_keys(mongo_uri, database)
    assert "laps?session_key=9468" not in stored
    assert {
        "meetings?year=2024",
        "sessions?date_end<2025-01-01T00%3A00%3A00%2B00%3A00&year=2024",
    } <= stored
    assert len(stored) < SEASON_REQUESTS


def test_telemetry_of_a_session_that_has_not_settled_exits_1(
    database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = run(["telemetry", "--session-key", "9472"], clock=RACE_END)

    assert exit_code == 1
    assert capsys.readouterr().err == (
        "ingestion failed: session 9472 ends at 2024-03-02T17:00:00+00:00; "
        "it can be ingested from 2024-03-02T23:00:00+00:00\n"
    )


def test_the_default_clock_cuts_the_current_season_at_the_settle_time(
    mongo_uri: str, database: str
) -> None:
    current_year = datetime.now(UTC).year

    exit_code = main(
        ["season", "--year", str(current_year)], transport=httpx2.MockTransport(openf1)
    )

    index_keys = [key for key in stored_keys(mongo_uri, database) if key.startswith("sessions?")]
    assert exit_code == 0
    assert len(index_keys) == 1
    cutoff = datetime.fromisoformat(unquote(index_keys[0].split("date_end<")[1].split("&")[0]))
    expected = datetime.now(UTC) - timedelta(hours=6)
    assert timedelta(0) <= expected - cutoff < timedelta(hours=1)


def test_telemetry_ingests_one_session(
    mongo_uri: str, database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = run(["telemetry", "--session-key", "9472"])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        f"ingested 1 sessions: {TELEMETRY_REQUESTS} requests, "
        f"{TELEMETRY_REQUESTS} fetched, 0 already stored\n"
    )
    assert len(stored_keys(mongo_uri, database)) == TELEMETRY_REQUESTS


def test_missing_configuration_fails_before_any_request(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MONGO_URI")

    with pytest.raises(ValidationError, match="mongo_uri"):
        run(["season", "--year", "2024"])


def test_an_unknown_session_type_is_rejected_by_the_parser(database: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(["season", "--year", "2024", "--session-type", "Sprint"])

    assert exit_info.value.code == 2
