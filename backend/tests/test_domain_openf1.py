from datetime import UTC, datetime, timedelta

import pytest

from f1_strategy.domain.openf1 import (
    Endpoint,
    JsonObject,
    OpenF1PayloadError,
    Param,
    RawRequest,
    Session,
    SessionType,
    drivers_request,
    meetings_request,
    parse_driver_numbers,
    parse_sessions,
    season_cutoff,
    season_sessions_request,
    session_request,
    session_requests,
    telemetry_requests,
)
from tests.factories import DRIVERS, RACE_END, RACE_KEY, RACE_START, session_row

HALF_HOUR = timedelta(minutes=30)


def race(duration_min: int = 120) -> Session:
    return Session(
        session_key=RACE_KEY,
        session_type=SessionType.RACE,
        date_start=RACE_START,
        date_end=RACE_START + timedelta(minutes=duration_min),
        is_cancelled=False,
    )


def test_request_key_is_endpoint_plus_sorted_encoded_params() -> None:
    request = RawRequest.of(
        Endpoint.CAR_DATA,
        {
            Param.SESSION_KEY: RACE_KEY,
            Param.DRIVER_NUMBER: 1,
            Param.DATE_BEFORE: "2024-03-02T15:30:00+00:00",
            Param.DATE_FROM: "2024-03-02T15:00:00+00:00",
        },
    )

    assert request.query == (
        "date<2024-03-02T15%3A30%3A00%2B00%3A00"
        "&date>=2024-03-02T15%3A00%3A00%2B00%3A00&driver_number=1&session_key=9472"
    )
    assert request.key == f"car_data?{request.query}"


def test_request_key_does_not_depend_on_param_order() -> None:
    first = RawRequest.of(Endpoint.LAPS, {Param.SESSION_KEY: 1, Param.DRIVER_NUMBER: 2})
    second = RawRequest.of(Endpoint.LAPS, {Param.DRIVER_NUMBER: 2, Param.SESSION_KEY: 1})

    assert first == second
    assert first.key == "laps?driver_number=2&session_key=1"


def test_index_requests() -> None:
    assert meetings_request(2024).key == "meetings?year=2024"
    assert season_sessions_request(2024, datetime(2025, 1, 1, tzinfo=UTC)).key == (
        "sessions?date_end<2025-01-01T00%3A00%3A00%2B00%3A00&year=2024"
    )
    assert session_request(RACE_KEY).key == "sessions?session_key=9472"
    assert drivers_request(RACE_KEY).key == "drivers?session_key=9472"


def test_session_key_is_read_from_params() -> None:
    assert session_request(RACE_KEY).session_key == RACE_KEY
    assert season_sessions_request(2024, RACE_END).session_key is None


SETTLE = timedelta(hours=6)


@pytest.mark.parametrize(
    "now",
    [datetime(2025, 2, 1, tzinfo=UTC), datetime(2031, 6, 1, 12, 34, tzinfo=UTC)],
)
def test_a_settled_season_is_cut_at_its_end_whenever_it_is_read(now: datetime) -> None:
    assert season_cutoff(2024, now, SETTLE) == datetime(2025, 1, 1, tzinfo=UTC)


def test_a_season_in_progress_is_cut_at_the_settle_time_truncated_to_the_hour() -> None:
    now = datetime(2026, 10, 27, 3, 28, 3, 123, tzinfo=UTC)

    assert season_cutoff(2026, now, SETTLE) == datetime(2026, 10, 26, 21, tzinfo=UTC)


def test_the_new_year_does_not_cut_a_season_before_its_last_sessions_settle() -> None:
    new_year = datetime(2025, 1, 1, 3, tzinfo=UTC)

    assert season_cutoff(2024, new_year, SETTLE) == datetime(2024, 12, 31, 21, tzinfo=UTC)


def test_a_future_season_is_cut_before_anything_settled() -> None:
    now = datetime(2026, 10, 27, 3, tzinfo=UTC)

    assert season_cutoff(2027, now, SETTLE) == datetime(2026, 10, 26, 21, tzinfo=UTC)


def test_a_session_settles_its_settle_time_after_it_ends() -> None:
    assert race().settles_at(SETTLE) == datetime(2024, 3, 2, 23, tzinfo=UTC)


def test_race_plan_has_intervals_and_overtakes_but_no_starting_grid() -> None:
    requests = session_requests(race())

    assert [request.endpoint for request in requests] == [
        Endpoint.DRIVERS,
        Endpoint.LAPS,
        Endpoint.STINTS,
        Endpoint.PIT,
        Endpoint.INTERVALS,
        Endpoint.POSITION,
        Endpoint.RACE_CONTROL,
        Endpoint.WEATHER,
        Endpoint.SESSION_RESULT,
        Endpoint.OVERTAKES,
        Endpoint.TEAM_RADIO,
    ]
    assert {request.params for request in requests} == {((Param.SESSION_KEY, RACE_KEY),)}


def test_qualifying_plan_has_starting_grid_but_no_race_only_endpoints() -> None:
    qualifying = Session(9468, SessionType.QUALIFYING, RACE_START, RACE_END, is_cancelled=False)

    endpoints = {request.endpoint for request in session_requests(qualifying)}

    assert Endpoint.STARTING_GRID in endpoints
    assert endpoints.isdisjoint({Endpoint.INTERVALS, Endpoint.OVERTAKES})


@pytest.mark.parametrize("session_type", list(SessionType))
def test_no_session_plan_asks_for_telemetry(session_type: SessionType) -> None:
    session = Session(1, session_type, RACE_START, RACE_END, is_cancelled=False)

    endpoints = {request.endpoint for request in session_requests(session)}

    assert endpoints.isdisjoint({Endpoint.CAR_DATA, Endpoint.LOCATION})


def test_telemetry_splits_each_driver_into_windows_from_the_session_start() -> None:
    requests = telemetry_requests(race(), [16, 1], HALF_HOUR)

    assert len(requests) == 2 * 2 * 4
    first_driver_car_data = [
        dict(request.params)
        for request in requests
        if request.endpoint == Endpoint.CAR_DATA and dict(request.params)[Param.DRIVER_NUMBER] == 1
    ]
    assert [(p[Param.DATE_FROM], p[Param.DATE_BEFORE]) for p in first_driver_car_data] == [
        ("2024-03-02T15:00:00+00:00", "2024-03-02T15:30:00+00:00"),
        ("2024-03-02T15:30:00+00:00", "2024-03-02T16:00:00+00:00"),
        ("2024-03-02T16:00:00+00:00", "2024-03-02T16:30:00+00:00"),
        ("2024-03-02T16:30:00+00:00", "2024-03-02T17:00:00+00:00"),
    ]


def test_the_last_telemetry_window_covers_an_uneven_session_end() -> None:
    requests = telemetry_requests(race(duration_min=70), [1], HALF_HOUR)

    assert len(requests) == 2 * 3
    assert dict(requests[2].params)[Param.DATE_BEFORE] == "2024-03-02T16:30:00+00:00"


def test_a_session_with_no_duration_has_no_telemetry_requests() -> None:
    assert telemetry_requests(race(duration_min=0), [1], HALF_HOUR) == ()


def test_a_session_without_drivers_has_no_telemetry_requests() -> None:
    assert telemetry_requests(race(), [], HALF_HOUR) == ()


@pytest.mark.parametrize("window", [timedelta(0), timedelta(minutes=-5)])
def test_telemetry_window_must_be_positive(window: timedelta) -> None:
    with pytest.raises(ValueError, match="telemetry window must be positive"):
        telemetry_requests(race(), [1], window)


def test_parse_sessions_maps_raw_values_to_typed_sessions() -> None:
    sessions = parse_sessions([session_row(RACE_KEY, "Race", is_cancelled=True)])

    assert sessions == [
        Session(RACE_KEY, SessionType.RACE, RACE_START, RACE_END, is_cancelled=True)
    ]


def test_parse_sessions_of_an_empty_payload_is_empty() -> None:
    assert parse_sessions([]) == []


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (session_row(1, "Sprint Shootout"), "unknown session_type 'Sprint Shootout'"),
        ({**session_row(1, "Race"), "session_type": None}, "session_type must be a string"),
        ({**session_row(1, "Race"), "session_key": "1"}, "session_key must be an integer"),
        ({**session_row(1, "Race"), "session_key": True}, "session_key must be an integer"),
        ({**session_row(1, "Race"), "is_cancelled": 0}, "is_cancelled must be a boolean"),
        (session_row(1, "Race", date_start="2024-03-02T15:00:00"), "date_start has no timezone"),
        (session_row(1, "Race", date_end="tomorrow"), "date_end is not an ISO timestamp"),
    ],
)
def test_parse_sessions_rejects_a_malformed_row(row: JsonObject, message: str) -> None:
    with pytest.raises(OpenF1PayloadError, match=message):
        parse_sessions([row])


def test_parse_driver_numbers_dedupes_and_sorts() -> None:
    assert parse_driver_numbers([*DRIVERS, DRIVERS[0]]) == [1, 16]


def test_parse_driver_numbers_rejects_a_missing_number() -> None:
    with pytest.raises(OpenF1PayloadError, match="driver_number must be an integer, got None"):
        parse_driver_numbers([{"session_key": RACE_KEY}])
