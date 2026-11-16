"""Readiness and the validation error shape, over a real PostgreSQL and Redis (ADR 0016)."""

import asyncio
from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager, contextmanager

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from f1_strategy.adapters.http.app import create_app
from f1_strategy.adapters.http.services import ApiServices, api_services
from f1_strategy.adapters.settings import ApiSettings

CLOSED_PORT_REDIS = "redis://127.0.0.1:1/0"
CLOSED_PORT_POSTGRES = "postgresql://f1:f1@127.0.0.1:1/f1"


@contextmanager
def client_for(settings: ApiSettings) -> Iterator[TestClient]:
    def services() -> AbstractAsyncContextManager[ApiServices]:
        return api_services(settings)

    options = {"loop_factory": asyncio.SelectorEventLoop}
    with TestClient(create_app(services), backend_options=options) as test_client:
        yield test_client


def test_the_api_is_ready_when_postgres_and_redis_answer(client: TestClient) -> None:
    response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"postgres": "ok", "redis": "ok"},
    }


def test_redis_down_makes_the_api_not_ready_and_is_logged(
    settings: ApiSettings, caplog: pytest.LogCaptureFixture
) -> None:
    # Above the 2 s Windows takes to refuse a closed local port, so the refusal is what is seen.
    down = settings.model_copy(
        update={
            "redis_uri": SecretStr(CLOSED_PORT_REDIS),
            "redis_timeout_s": 3,
            "readiness_timeout_s": 5,
        }
    )

    with client_for(down) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "not answering: redis",
        "code": "not_ready",
        "request_id": response.headers["x-request-id"],
        "dependencies": {"postgres": "ok", "redis": "failed"},
    }
    assert [
        (record.getMessage(), getattr(record, "fields", None))
        for record in caplog.records
        if record.name == "f1_strategy.http" and record.levelname == "WARNING"
    ] == [("dependency_unavailable", {"dependency": "redis", "error": "ConnectionError"})]


def test_postgres_down_names_the_pool_error(settings: ApiSettings) -> None:
    down = settings.model_copy(
        update={
            "postgres_uri": SecretStr(CLOSED_PORT_POSTGRES),
            "postgres_connect_timeout_s": 1,
            "readiness_timeout_s": 5,
        }
    )

    with client_for(down) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["dependencies"] == {"postgres": "failed", "redis": "ok"}


def test_a_request_outside_the_schema_answers_each_invalid_field_without_its_value(
    client: TestClient,
) -> None:
    response = client.post("/api/replays", json={"session_key": "secret-value", "speed": 3})

    assert response.status_code == 422
    assert response.json() == {
        "detail": "the request does not match the API schema",
        "code": "invalid_request",
        "request_id": response.headers["x-request-id"],
        "errors": [
            {
                "loc": ["body", "session_key"],
                "msg": "Input should be a valid integer, unable to parse string as an integer",
                "type": "int_parsing",
            },
            {
                "loc": ["body", "speed"],
                "msg": "Input should be 1, 2, 5, 10, 20 or 60",
                "type": "enum",
            },
        ],
    }
    assert "secret-value" not in response.text
