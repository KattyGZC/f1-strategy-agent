import json

from f1_strategy.adapters.http.openapi import render_openapi


def test_openapi_documents_the_health_response() -> None:
    document = json.loads(render_openapi())

    assert document["components"]["schemas"]["HealthResponse"] == {
        "properties": {"status": {"const": "ok", "title": "Status", "type": "string"}},
        "required": ["status"],
        "title": "HealthResponse",
        "type": "object",
    }
    assert set(document["paths"]) == {"/api/health"}


def test_openapi_rendering_is_stable() -> None:
    assert render_openapi() == render_openapi()
