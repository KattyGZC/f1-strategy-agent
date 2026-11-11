import asyncio
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, TypeAdapter
from redis.asyncio import Redis

from f1_strategy.adapters.http.app import create_app
from f1_strategy.adapters.replay_events import ReplayEvent, wire_event
from f1_strategy.adapters.replay_store import RedisReplayStore
from f1_strategy.adapters.settings import ApiSettings
from tests.http.api import EVENTS, LAP_1_S, SESSION

UNKNOWN_SESSION = 9999
WIRE = TypeAdapter(ReplayEvent)


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
        # nginx in front of the API would hold the events back without it.
        assert response.headers["x-accel-buffering"] == "no"
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


def test_a_stopped_replay_is_gone_and_frees_its_place(client: TestClient) -> None:
    stopped = start(client, speed=1)
    start(client)

    response = client.delete(f"/api/replays/{stopped}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/api/replays/{stopped}").status_code == 404
    assert client.get(f"/api/replays/{stopped}/events").status_code == 404
    assert client.post("/api/replays", json={"session_key": SESSION, "speed": 1}).status_code == 201


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/replays/missing"),
        ("POST", "/api/replays/missing/pause"),
        ("POST", "/api/replays/missing/resume"),
        ("POST", "/api/replays/missing/seek"),
        ("DELETE", "/api/replays/missing"),
        ("GET", "/api/replays/missing/events"),
    ],
)
def test_an_unknown_replay_is_not_found(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, json={"lap_number": 1})

    assert response.status_code == 404
    assert response.json() == {"detail": "replay missing does not exist or has expired"}


@pytest.mark.parametrize(
    ("method", "url", "body", "headers"),
    [
        ("POST", "/api/replays", {"session_key": SESSION, "speed": 3}, None),
        ("POST", "/api/replays", {"session_key": 0, "speed": 1}, None),
        ("PUT", "/api/replays/abc/speed", {"speed": 7}, None),
        ("POST", "/api/replays/abc/seek", {"lap_number": 0}, None),
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
    seek = client.post(f"/api/replays/{replay_id}/seek", json={"lap_number": 1})

    assert received[-1]["event"] == "replay_failed"
    assert json.loads(received[-1]["data"]) == {"kind": "replay_failed", "message": "boom"}
    assert "id" not in received[-1]
    assert client.get(f"/api/replays/{replay_id}").json()["failure"] == "boom"
    assert seek.status_code == 409
    assert seek.json() == {"detail": f"replay {replay_id} failed and cannot move: boom"}


def test_the_app_without_its_lifespan_has_no_services() -> None:
    with pytest.raises(
        RuntimeError,
        match=r"^the API services are not running; start the app with its lifespan$",
    ):
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


def test_a_seek_moves_the_replay_and_its_stream_restarts_from_a_reset(
    client: TestClient,
) -> None:
    replay_id = start(client, speed=1)
    up_to_lap = [event for event in EVENTS if (event.at - EVENTS[0].at).total_seconds() <= LAP_1_S]

    response = client.post(f"/api/replays/{replay_id}/seek", json={"lap_number": 1})
    received = sse_events(client, replay_id, 1 + len(up_to_lap))

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["speed"], body["session_s"]) == ("playing", 1, LAP_1_S)
    reset, *rebuilt = received
    assert reset == {
        "event": "replay_reset",
        "id": "1-0",
        "data": json.dumps(
            {"kind": "replay_reset", "lap_number": 1, "session_s": LAP_1_S}, separators=(",", ":")
        ),
    }
    assert [event["id"] for event in rebuilt] == [f"1-{n + 1}" for n in range(len(up_to_lap))]
    assert [WIRE.validate_json(event["data"]) for event in rebuilt] == [
        wire_event(event) for event in up_to_lap
    ]


def test_a_lap_no_driver_started_is_not_found(client: TestClient) -> None:
    replay_id = start(client, speed=1)

    response = client.post(f"/api/replays/{replay_id}/seek", json={"lap_number": 2})

    assert response.status_code == 404
    assert response.json() == {"detail": f"session {SESSION} has no start for lap 2"}
    assert client.get(f"/api/replays/{replay_id}").json()["status"] == "playing"
