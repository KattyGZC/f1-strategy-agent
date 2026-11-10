import json

from f1_strategy.adapters.http.openapi import render_openapi
from f1_strategy.domain.replay import EventKind


def test_openapi_documents_the_health_response() -> None:
    document = json.loads(render_openapi())

    assert document["components"]["schemas"]["HealthResponse"] == {
        "properties": {"status": {"const": "ok", "title": "Status", "type": "string"}},
        "required": ["status"],
        "title": "HealthResponse",
        "type": "object",
    }
    assert set(document["paths"]) == {
        "/api/health",
        "/api/replays",
        "/api/replays/{replay_id}",
        "/api/replays/{replay_id}/pause",
        "/api/replays/{replay_id}/resume",
        "/api/replays/{replay_id}/speed",
        "/api/replays/{replay_id}/events",
        "/api/sessions",
        "/api/sessions/{session_key}",
    }


def test_openapi_documents_every_replayed_event_and_the_failure() -> None:
    document = json.loads(render_openapi())

    stream = document["paths"]["/api/replays/{replay_id}/events"]["get"]["responses"]
    data = stream["200"]["content"]["text/event-stream"]["itemSchema"]["properties"]["data"]
    refs = {ref["$ref"].rsplit("/", 1)[1] for ref in data["contentSchema"]["anyOf"]}
    union = document["components"]["schemas"]["ReplayEvent"]
    kinds = {
        document["components"]["schemas"][ref.rsplit("/", 1)[1]]["properties"]["kind"]["const"]
        for ref in union["discriminator"]["mapping"].values()
    }
    assert {"ReplayEvent", "ReplayFailedEvent"} <= refs
    assert kinds == {kind.value for kind in EventKind}
    assert stream["404"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}
    }


def test_openapi_rendering_is_stable() -> None:
    assert render_openapi() == render_openapi()
