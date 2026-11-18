import pytest
from fastapi.testclient import TestClient

from tests.http.api import CALIBRATED_DRIVER, SESSION, error_body

type Json = dict[str, object]

SOFT_THEN_HARD: list[Json] = [
    {"compound": "SOFT", "laps": 4, "tyre_age_at_start_laps": 0},
    {"compound": "HARD", "laps": 6, "tyre_age_at_start_laps": 0},
]
HARD_ONLY: list[Json] = [{"compound": "HARD", "laps": 10, "tyre_age_at_start_laps": 0}]
DRY_RACE_NOT_MODELLED = [
    "standing_start", "starting_fuel", "wind", "driver_aggressiveness", "track_temperature",
]  # fmt: skip


def lap(lap_number: int, age: int, lap_time_s: float, *, extrapolated: bool = False) -> Json:
    return {
        "lap_number": lap_number,
        "tyre_age_laps": age,
        "lap_time_s": lap_time_s,
        "extrapolated": extrapolated,
    }


def body(*strategies: list[Json], **fields: object) -> Json:
    return {"session_key": SESSION, "strategies": list(strategies), **fields}


@pytest.mark.usefixtures("calibrated")
def test_strategies_are_simulated_and_timed_against_the_fastest(client: TestClient) -> None:
    response = client.post("/api/simulations", json=body(SOFT_THEN_HARD, HARD_ONLY))

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "outcome": "simulated",
                "stints": [
                    {"compound": "SOFT", "laps": [
                        lap(1, 0, 90.0, extrapolated=True), lap(2, 1, 90.05), lap(3, 2, 90.1),
                        lap(4, 3, 90.15),
                    ]},
                    {"compound": "HARD", "laps": [
                        lap(5, 0, 90.8, extrapolated=True),
                        *(lap(number, number - 5, 90.8) for number in range(6, 11)),
                    ]},
                ],
                "stops": [{"in_lap": 4, "pit_loss_s": 20.0}],
                "total_s": 925.1,
                "gap_to_fastest_s": 15.1,
                "caveats": ["extrapolated_tyre_age"],
            },
            {
                "outcome": "simulated",
                "stints": [{"compound": "HARD", "laps": [
                    lap(1, 0, 91.0, extrapolated=True),
                    *(lap(number, number - 1, 91.0) for number in range(2, 10)),
                    lap(10, 9, 91.0, extrapolated=True),
                ]}],
                "stops": [],
                "total_s": 910.0,
                "gap_to_fastest_s": 0.0,
                "caveats": ["extrapolated_tyre_age", "one_dry_compound"],
            },
        ],
        "not_modelled": DRY_RACE_NOT_MODELLED,
    }  # fmt: skip


@pytest.mark.usefixtures("calibrated")
def test_a_strategy_the_race_cannot_run_is_rejected_next_to_the_others(
    client: TestClient,
) -> None:
    medium: list[Json] = [{"compound": "MEDIUM", "laps": 10, "tyre_age_at_start_laps": 0}]
    short: list[Json] = [{"compound": "HARD", "laps": 9, "tyre_age_at_start_laps": 0}]

    response = client.post("/api/simulations", json=body(medium, HARD_ONLY, short))

    assert response.status_code == 200
    first, second, third = response.json()["results"]
    assert first == {"outcome": "rejected", "reason": "compound_not_calibrated", "stint_number": 1}
    assert (second["outcome"], second["total_s"], second["gap_to_fastest_s"]) == (
        "simulated",
        910.0,
        0.0,
    )
    assert third == {"outcome": "rejected", "reason": "laps_do_not_add_up", "stint_number": None}


@pytest.mark.usefixtures("calibrated")
def test_a_drivers_pace_moves_every_lap(client: TestClient) -> None:
    response = client.post(
        "/api/simulations", json=body(HARD_ONLY, driver_number=CALIBRATED_DRIVER)
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["total_s"] == 913.0


@pytest.mark.usefixtures("calibrated")
def test_a_driver_without_a_calibrated_pace_is_not_found(client: TestClient) -> None:
    response = client.post("/api/simulations", json=body(HARD_ONLY, driver_number=99))

    assert response.status_code == 404
    assert response.json() == error_body(
        response, "driver_not_calibrated", "driver 99 has no calibrated pace in this race"
    )


def test_a_race_without_a_calibration_is_not_found(client: TestClient) -> None:
    response = client.post("/api/simulations", json=body(HARD_ONLY))

    assert response.status_code == 404
    assert response.json() == error_body(
        response,
        "race_not_calibrated",
        f"race {SESSION} has no calibration; run the calibration first",
    )


@pytest.mark.parametrize(
    "request_body",
    [
        pytest.param(body(), id="no strategy"),
        pytest.param(body(*[HARD_ONLY] * 5), id="5 strategies"),
        pytest.param(body([]), id="no stint"),
        pytest.param(body([HARD_ONLY[0]] * 7), id="7 stints"),
        pytest.param(body([{**HARD_ONLY[0], "laps": 0}]), id="0 laps"),
        pytest.param(body([{**HARD_ONLY[0], "tyre_age_at_start_laps": -1}]), id="age -1"),
        pytest.param(body([{**HARD_ONLY[0], "tyre_age_at_start_laps": 100}]), id="age 100"),
        pytest.param(body([{**HARD_ONLY[0], "compound": "SUPERSOFT"}]), id="unknown compound"),
        pytest.param(body(HARD_ONLY, driver_number=0), id="driver 0"),
        pytest.param(body(HARD_ONLY, session_key=0), id="session 0"),
    ],
)
def test_a_simulation_outside_the_schema_bounds_is_rejected_at_the_boundary(
    client: TestClient, request_body: Json
) -> None:
    response = client.post("/api/simulations", json=request_body)

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


@pytest.mark.usefixtures("calibrated")
def test_the_largest_simulation_the_schema_accepts_is_answered(client: TestClient) -> None:
    worn_softs: list[Json] = [{"compound": "SOFT", "laps": 1, "tyre_age_at_start_laps": 99}] * 5
    six_stints = [*worn_softs, {"compound": "HARD", "laps": 5, "tyre_age_at_start_laps": 0}]

    response = client.post("/api/simulations", json=body(*[six_stints] * 4))

    assert response.status_code == 200
    assert [result["outcome"] for result in response.json()["results"]] == ["simulated"] * 4
