import pytest
from fastapi.testclient import TestClient

from tests.http.api import SESSION, SHORT_RACE

UNKNOWN_SESSION = 9999

SESSION_FIELDS = {
    "session_key": SESSION,
    "session_type": "Race",
    "session_name": "Race",
    "date_start": "2024-03-02T15:00:00Z",
    "year": 2024,
    "meeting_name": "Bahrain Grand Prix",
    "circuit_short_name": "Sakhir",
    "country_name": "Bahrain",
}


def test_the_loaded_sessions_are_listed(client: TestClient) -> None:
    response = client.get("/api/sessions")

    assert response.status_code == 200
    assert response.json() == [SESSION_FIELDS]


def test_a_session_reads_with_its_drivers_by_number(client: TestClient) -> None:
    drivers = sorted(SHORT_RACE.drivers, key=lambda driver: driver.driver_number)

    response = client.get(f"/api/sessions/{SESSION}")

    assert response.status_code == 200
    assert response.json() == {
        **SESSION_FIELDS,
        "drivers": [
            {
                "driver_number": driver.driver_number,
                "name_acronym": driver.name_acronym,
                "full_name": driver.full_name,
                "team_name": driver.team_name,
                "team_colour": driver.team_colour,
            }
            for driver in drivers
        ],
    }


def test_a_session_not_in_the_clean_model_is_not_found(client: TestClient) -> None:
    response = client.get(f"/api/sessions/{UNKNOWN_SESSION}")

    assert response.status_code == 404
    assert response.json() == {"detail": f"session {UNKNOWN_SESSION} is not in the clean model"}


@pytest.mark.parametrize("session_key", ["0", "-1", "race"])
def test_an_invalid_session_key_is_rejected_at_the_boundary(
    client: TestClient, session_key: str
) -> None:
    assert client.get(f"/api/sessions/{session_key}").status_code == 422
