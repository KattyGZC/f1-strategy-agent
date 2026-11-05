import asyncio
import json
from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, TypeAdapter
from redis.asyncio import Redis

from f1_strategy.adapters.clean_store import PostgresCleanStore, connection_pool
from f1_strategy.adapters.http.app import create_app
from f1_strategy.adapters.http.services import ReplayServices, replay_services
from f1_strategy.adapters.migrate import upgrade
from f1_strategy.adapters.replay_events import ReplayEvent, wire_event
from f1_strategy.adapters.replay_store import RedisReplayStore
from f1_strategy.adapters.settings import ApiSettings
from f1_strategy.application.transform import Load, Version
from f1_strategy.domain.clean import CleanSession, clean_session, content_hash
from f1_strategy.domain.replay import LapCompleted, timeline
from tests.postgres import CONNECT_TIMEOUT_S, fresh_database
from tests.samples import RACE, sample

SESSION = int(RACE)
UNKNOWN_SESSION = 9999
WIRE = TypeAdapter(ReplayEvent)
WINDOW = timedelta(seconds=60)


def first_minute(session: CleanSession) -> CleanSession:
    """The session cut to its first minute of events, so a replay at 60x lasts one second."""
    cutoff = timeline(session).events[0].at + WINDOW
    ended_laps = {
        (event.payload.lap.driver_number, event.payload.lap.lap_number)
        for event in timeline(session).events
        if isinstance(event.payload, LapCompleted) and event.at < cutoff
    }
    return replace(
        session,
        laps=tuple(
            lap for lap in session.laps if (lap.driver_number, lap.lap_number) in ended_laps
        ),
        pits=tuple(row for row in session.pits if row.date < cutoff),
        intervals=tuple(row for row in session.intervals if row.date < cutoff),
        positions=tuple(row for row in session.positions if row.date < cutoff),
        race_control=tuple(row for row in session.race_control if row.date < cutoff),
        weather=tuple(row for row in session.weather if row.date < cutoff),
        overtakes=tuple(row for row in session.overtakes if row.date < cutoff),
        team_radio=tuple(row for row in session.team_radio if row.date < cutoff),
    )


SHORT_RACE = first_minute(clean_session(sample(RACE).raw()))
EVENTS = timeline(SHORT_RACE).events


async def load(postgres_uri: str, session: CleanSession) -> None:
    async with connection_pool(postgres_uri, 1, CONNECT_TIMEOUT_S) as pool:
        store = PostgresCleanStore(pool)
        version = Version("input-1", "1")
        async with store.claim(SESSION, version, EVENTS[0].at) as claim:
            assert claim is not None
            await claim.replace(Load(session, version, content_hash(session), EVENTS[0].at))


async def flush(redis_uri: str) -> None:
    client = Redis.from_url(redis_uri)
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def settings(postgres_server_uri: str, redis_server_uri: str) -> ApiSettings:
    postgres_uri = fresh_database(postgres_server_uri)
    upgrade(postgres_uri, CONNECT_TIMEOUT_S)
    asyncio.run(load(postgres_uri, SHORT_RACE), loop_factory=asyncio.SelectorEventLoop)
    asyncio.run(flush(redis_server_uri))
    return ApiSettings(
        postgres_uri=SecretStr(postgres_uri),
        postgres_connect_timeout_s=CONNECT_TIMEOUT_S,
        postgres_pool_size=2,
        redis_uri=SecretStr(redis_server_uri),
        redis_max_connections=8,
        redis_timeout_s=5,
        replay_max_active=2,
        replay_idle_ttl_s=60,
        replay_tick_s=0.02,
        replay_lease_s=1,
    )


@pytest.fixture
def client(settings: ApiSettings) -> Iterator[TestClient]:
    def services() -> AbstractAsyncContextManager[ReplayServices]:
        return replay_services(settings)

    # psycopg's async driver needs the selector loop, also in the test client's thread.
    options = {"loop_factory": asyncio.SelectorEventLoop}
    with TestClient(create_app(services), backend_options=options) as test_client:
        yield test_client


def start(client: TestClient, speed: int = 60) -> str:
    response = client.post("/api/replays", json={"session_key": SESSION, "speed": speed})
    assert response.status_code == 201, response.text
    replay_id = response.json()["replay_id"]
    assert isinstance(replay_id, str)
    return replay_id


def sse_events(
    client: TestClient, replay_id: str, count: int, headers: dict[str, str] | None = None
) -> list[dict[str, str]]:
    """The first `count` events of the replay's stream, each as its SSE fields."""
    received: list[dict[str, str]] = []
    fields: dict[str, str] = {}
    with client.stream("GET", f"/api/replays/{replay_id}/events", headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith(":"):
                continue
            if line:
                name, _, value = line.partition(": ")
                fields[name] = value
                continue
            if fields:
                received.append(fields)
                fields = {}
            if len(received) == count:
                break
    return received


def test_a_replay_streams_every_event_of_its_session_in_order(client: TestClient) -> None:
    replay_id = start(client)

    received = sse_events(client, replay_id, len(EVENTS))

    assert [event["id"] for event in received] == [f"0-{n + 1}" for n in range(len(EVENTS))]
    assert [event["event"] for event in received] == [event.kind for event in EVENTS]
    assert [WIRE.validate_json(event["data"]) for event in received] == [
        wire_event(event) for event in EVENTS
    ]


def test_a_reconnecting_viewer_resumes_after_its_last_event(client: TestClient) -> None:
    replay_id = start(client)
    sse_events(client, replay_id, len(EVENTS))

    received = sse_events(client, replay_id, 2, headers={"Last-Event-ID": "0-3"})

    assert [event["id"] for event in received] == ["0-4", "0-5"]


def test_a_started_replay_reports_its_state(client: TestClient) -> None:
    response = client.post("/api/replays", json={"session_key": SESSION, "speed": 10})

    body = response.json()
    assert response.status_code == 201
    assert body["session_key"] == SESSION
    assert body["status"] == "playing"
    assert body["speed"] == 10
    assert body["failure"] is None
    assert 0 <= body["session_s"] < 10


def test_controls_pause_resume_and_change_the_speed(client: TestClient) -> None:
    replay_id = start(client, speed=1)

    paused = client.post(f"/api/replays/{replay_id}/pause").json()
    faster = client.put(f"/api/replays/{replay_id}/speed", json={"speed": 20}).json()
    still_paused = client.get(f"/api/replays/{replay_id}").json()
    resumed = client.post(f"/api/replays/{replay_id}/resume").json()

    assert (paused["status"], paused["speed"]) == ("paused", 1)
    assert (faster["status"], faster["speed"]) == ("paused", 20)
    assert still_paused["session_s"] == paused["session_s"]
    assert (resumed["status"], resumed["speed"]) == ("playing", 20)
    assert resumed["session_s"] == pytest.approx(paused["session_s"], abs=0.5)


def test_a_session_not_in_the_clean_model_is_not_found(client: TestClient) -> None:
    response = client.post("/api/replays", json={"session_key": UNKNOWN_SESSION, "speed": 1})

    assert response.status_code == 404
    assert response.json() == {"detail": f"session {UNKNOWN_SESSION} is not in the clean model"}


def test_a_replay_past_the_limit_is_refused(client: TestClient) -> None:
    start(client)
    start(client)

    response = client.post("/api/replays", json={"session_key": SESSION, "speed": 1})

    assert response.status_code == 503
    assert response.json() == {"detail": "the number of active replays is at its limit"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/replays/missing"),
        ("POST", "/api/replays/missing/pause"),
        ("POST", "/api/replays/missing/resume"),
        ("GET", "/api/replays/missing/events"),
    ],
)
def test_an_unknown_replay_is_not_found(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path)

    assert response.status_code == 404
    assert response.json() == {"detail": "replay missing does not exist or has expired"}


@pytest.mark.parametrize(
    ("method", "url", "body", "headers"),
    [
        ("POST", "/api/replays", {"session_key": SESSION, "speed": 3}, None),
        ("POST", "/api/replays", {"session_key": 0, "speed": 1}, None),
        ("PUT", "/api/replays/abc/speed", {"speed": 7}, None),
        ("GET", "/api/replays/not$an$id", None, None),
        ("GET", "/api/replays/abc/events", None, {"Last-Event-ID": "latest"}),
    ],
)
def test_invalid_input_is_rejected_at_the_boundary(
    client: TestClient,
    method: str,
    url: str,
    body: dict[str, int] | None,
    headers: dict[str, str] | None,
) -> None:
    response = client.request(method, url, json=body, headers=headers)

    assert response.status_code == 422


def test_a_failed_replay_ends_its_stream_with_the_failure(
    client: TestClient, settings: ApiSettings
) -> None:
    replay_id = start(client, speed=1)

    async def fail() -> None:
        redis = Redis.from_url(settings.redis_uri.get_secret_value())
        replays = RedisReplayStore(redis, settings.replay_max_active, settings.replay_idle_ttl_s)
        await replays.update(replay_id, lambda state: replace(state, failure="boom"))
        await redis.aclose()

    asyncio.run(fail())

    received = sse_events(client, replay_id, 10)

    assert received[-1]["event"] == "replay_failed"
    assert json.loads(received[-1]["data"]) == {"kind": "replay_failed", "message": "boom"}
    assert "id" not in received[-1]
    assert client.get(f"/api/replays/{replay_id}").json()["failure"] == "boom"


def test_the_app_without_its_lifespan_has_no_replay_services() -> None:
    with pytest.raises(RuntimeError, match="not running"):
        TestClient(create_app()).get("/api/replays/abc")


def test_the_production_services_come_from_the_settings(
    monkeypatch: pytest.MonkeyPatch, settings: ApiSettings
) -> None:
    for name, value in settings.model_dump().items():
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        monkeypatch.setenv(name.upper(), str(secret))
    options = {"loop_factory": asyncio.SelectorEventLoop}

    with TestClient(create_app(), backend_options=options) as test_client:
        response = test_client.post("/api/replays", json={"session_key": SESSION, "speed": 1})

    assert response.status_code == 201
