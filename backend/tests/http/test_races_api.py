import pytest
from fastapi.testclient import TestClient

from tests.http.api import CALIBRATED_DRIVER, SESSION, error_body

RACE_FIELDS = {
    "session_key": SESSION,
    "date_start": "2024-03-02T15:00:00Z",
    "year": 2024,
    "meeting_name": "Bahrain Grand Prix",
    "circuit_short_name": "Sakhir",
    "country_name": "Bahrain",
    "race_laps": 10,
}


@pytest.mark.usefixtures("calibrated")
def test_the_calibrated_races_are_listed(client: TestClient) -> None:
    response = client.get("/api/races")

    assert response.status_code == 200
    assert response.json() == [RACE_FIELDS]


def test_a_race_loaded_but_not_calibrated_is_not_listed(client: TestClient) -> None:
    response = client.get("/api/races")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.usefixtures("calibrated")
def test_a_race_reads_with_what_its_model_carries(client: TestClient) -> None:
    response = client.get(f"/api/races/{SESSION}")

    assert response.status_code == 200
    assert response.json() == {
        "session_key": SESSION,
        "race_laps": 10,
        "compounds": [
            {"compound": "SOFT", "min_tyre_age_laps": 1, "max_tyre_age_laps": 5,
             "residual_rmse_s": 0.4},
            {"compound": "HARD", "min_tyre_age_laps": 1, "max_tyre_age_laps": 8,
             "residual_rmse_s": 0.4},
        ],
        "driver_numbers": [CALIBRATED_DRIVER],
        "residual_rmse_s": 0.4,
        "pit_loss": {"pit_loss_s": 20.0, "stops": 10, "reliable": True},
        "track_temperature": None,
        "rain_readings": 0,
        "not_modelled": [
            "standing_start", "starting_fuel", "wind", "driver_aggressiveness",
            "track_temperature",
        ],
    }  # fmt: skip


def test_a_race_without_a_calibration_is_not_found(client: TestClient) -> None:
    response = client.get(f"/api/races/{SESSION}")

    assert response.status_code == 404
    assert response.json() == error_body(
        response,
        "race_not_calibrated",
        f"race {SESSION} has no calibration; run the calibration first",
    )


@pytest.mark.parametrize("session_key", ["0", "-1", "race"])
def test_an_invalid_session_key_is_rejected_at_the_boundary(
    client: TestClient, session_key: str
) -> None:
    response = client.get(f"/api/races/{session_key}")

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
