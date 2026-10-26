from fastapi.testclient import TestClient

from f1_strategy.adapters.http.app import create_app


def test_health_returns_ok() -> None:
    response = TestClient(create_app()).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_not_served_outside_the_api_prefix() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 404
