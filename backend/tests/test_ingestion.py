import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from f1_strategy.application.ingestion import (
    IngestionReport,
    IngestSeason,
    IngestSessionTelemetry,
    SeasonNotFinishedError,
    SessionNotEndedError,
    SessionNotFoundError,
)
from f1_strategy.domain.openf1 import (
    JsonObject,
    RawRequest,
    RawResponse,
    SessionType,
    drivers_request,
    meetings_request,
    season_sessions_request,
    session_request,
)
from tests.factories import (
    AFTER_2024,
    CANCELLED_KEY,
    DRIVERS,
    PRACTICE_KEY,
    QUALIFYING_KEY,
    RACE_END,
    RACE_KEY,
    SEASON_2024,
    session_row,
)

FETCHED_AT = datetime(2026, 10, 26, tzinfo=UTC)
RACE_AND_QUALIFYING = frozenset({SessionType.RACE, SessionType.QUALIFYING})
RACE_ENDPOINT_COUNT = 11
QUALIFYING_ENDPOINT_COUNT = 10
HALF_HOUR = timedelta(minutes=30)


class SourceFailedError(Exception):
    pass


class FakeSource:
    def __init__(
        self, payloads: dict[str, list[JsonObject]], failing: frozenset[str] = frozenset()
    ) -> None:
        self._payloads = payloads
        self._failing = failing
        self.fetched: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def fetch(self, request: RawRequest) -> RawResponse:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        if request.key in self._failing:
            raise SourceFailedError(request.key)
        self.fetched.append(request.key)
        return RawResponse(request, self._payloads.get(request.key, []), FETCHED_AT)


class FakeStore:
    def __init__(self) -> None:
        self.responses: dict[str, RawResponse] = {}

    async def contains(self, request: RawRequest) -> bool:
        return request.key in self.responses

    async def rows(self, request: RawRequest) -> list[JsonObject] | None:
        stored = self.responses.get(request.key)
        return None if stored is None else stored.rows

    async def put(self, response: RawResponse) -> None:
        self.responses.setdefault(response.request.key, response)


def season_source(failing: frozenset[str] = frozenset()) -> FakeSource:
    return FakeSource({season_sessions_request(2024).key: SEASON_2024}, failing)


@pytest.mark.anyio
async def test_season_stores_the_index_and_every_endpoint_of_the_chosen_sessions() -> None:
    source, store = season_source(), FakeStore()

    report = await IngestSeason(source, store, max_concurrency=3)(
        2024, RACE_AND_QUALIFYING, AFTER_2024
    )

    expected = 2 + RACE_ENDPOINT_COUNT + QUALIFYING_ENDPOINT_COUNT
    assert report == IngestionReport(sessions=2, requests=expected, fetched=expected)
    assert sorted(source.fetched) == sorted(store.responses)
    assert meetings_request(2024).key in store.responses
    assert "intervals?session_key=9472" in store.responses
    assert "starting_grid?session_key=9468" in store.responses


@pytest.mark.anyio
async def test_season_skips_unchosen_and_cancelled_sessions() -> None:
    source, store = season_source(), FakeStore()

    await IngestSeason(source, store, max_concurrency=3)(2024, RACE_AND_QUALIFYING, AFTER_2024)

    stored_session_keys = {response.request.session_key for response in store.responses.values()}
    assert stored_session_keys == {None, RACE_KEY, QUALIFYING_KEY}
    assert PRACTICE_KEY not in stored_session_keys
    assert CANCELLED_KEY not in stored_session_keys


@pytest.mark.anyio
async def test_a_second_season_run_fetches_nothing() -> None:
    store = FakeStore()
    await IngestSeason(season_source(), store, max_concurrency=3)(
        2024, RACE_AND_QUALIFYING, AFTER_2024
    )
    second_source = season_source()

    report = await IngestSeason(second_source, store, max_concurrency=3)(
        2024, RACE_AND_QUALIFYING, AFTER_2024
    )

    assert second_source.fetched == []
    assert report.fetched == 0
    assert report.already_stored == report.requests == 2 + 21


@pytest.mark.anyio
async def test_a_failed_request_stops_the_run_with_its_own_error_and_a_rerun_resumes() -> None:
    store = FakeStore()
    failing = frozenset({"laps?session_key=9472"})

    with pytest.raises(SourceFailedError, match=r"laps\?session_key=9472"):
        await IngestSeason(season_source(failing), store, max_concurrency=1)(
            2024, RACE_AND_QUALIFYING, AFTER_2024
        )

    assert "laps?session_key=9472" not in store.responses
    stored_before_resume = set(store.responses)
    resumed_source = season_source()
    report = await IngestSeason(resumed_source, store, max_concurrency=3)(
        2024, RACE_AND_QUALIFYING, AFTER_2024
    )
    assert "laps?session_key=9472" in resumed_source.fetched
    assert stored_before_resume.isdisjoint(resumed_source.fetched)
    assert report.fetched == len(resumed_source.fetched)


@pytest.mark.anyio
async def test_season_never_exceeds_the_concurrency_bound() -> None:
    source = season_source()

    await IngestSeason(source, FakeStore(), max_concurrency=2)(
        2024, RACE_AND_QUALIFYING, AFTER_2024
    )

    assert source.max_in_flight == 2


@pytest.mark.parametrize("now_year", [2024, 2023])
@pytest.mark.anyio
async def test_an_unfinished_season_is_refused_before_any_request(now_year: int) -> None:
    source = season_source()

    with pytest.raises(SeasonNotFinishedError, match="season 2024 is not finished"):
        await IngestSeason(source, FakeStore(), max_concurrency=3)(
            2024, RACE_AND_QUALIFYING, datetime(now_year, 12, 31, tzinfo=UTC)
        )

    assert source.fetched == []


def test_concurrency_must_be_at_least_one() -> None:
    use_case = IngestSeason(season_source(), FakeStore(), max_concurrency=0)

    with pytest.raises(ValueError, match="max_concurrency must be at least 1, got 0"):
        asyncio.run(use_case(2024, RACE_AND_QUALIFYING, AFTER_2024))


def telemetry_source(session_rows: list[JsonObject]) -> FakeSource:
    return FakeSource(
        {
            session_request(RACE_KEY).key: session_rows,
            drivers_request(RACE_KEY).key: DRIVERS,
        }
    )


@pytest.mark.anyio
async def test_telemetry_stores_every_driver_window_of_both_endpoints() -> None:
    source, store = telemetry_source([session_row(RACE_KEY, "Race")]), FakeStore()

    report = await IngestSessionTelemetry(source, store, 3, HALF_HOUR)(RACE_KEY, AFTER_2024)

    telemetry = 2 * 2 * 4
    assert report == IngestionReport(sessions=1, requests=2 + telemetry, fetched=2 + telemetry)
    car_data_keys = [key for key in store.responses if key.startswith("car_data?")]
    location_keys = [key for key in store.responses if key.startswith("location?")]
    assert len(car_data_keys) == len(location_keys) == 2 * 4


@pytest.mark.anyio
async def test_telemetry_reuses_a_stored_driver_list() -> None:
    store = FakeStore()
    await store.put(RawResponse(drivers_request(RACE_KEY), DRIVERS, FETCHED_AT))
    source = telemetry_source([session_row(RACE_KEY, "Race")])

    await IngestSessionTelemetry(source, store, 3, HALF_HOUR)(RACE_KEY, AFTER_2024)

    assert drivers_request(RACE_KEY).key not in source.fetched


@pytest.mark.anyio
async def test_telemetry_of_a_session_that_has_not_ended_is_refused() -> None:
    source = telemetry_source([session_row(RACE_KEY, "Race")])
    before_the_end = RACE_END - timedelta(seconds=1)

    with pytest.raises(SessionNotEndedError, match="session 9472 ends at 2024-03-02T17:00:00"):
        await IngestSessionTelemetry(source, FakeStore(), 3, HALF_HOUR)(RACE_KEY, before_the_end)

    assert source.fetched == [session_request(RACE_KEY).key]


@pytest.mark.parametrize("session_rows", [[], [session_row(RACE_KEY, "Race")] * 2])
@pytest.mark.anyio
async def test_telemetry_needs_exactly_one_session(session_rows: list[JsonObject]) -> None:
    source = telemetry_source(session_rows)

    with pytest.raises(SessionNotFoundError, match=f"returned {len(session_rows)}"):
        await IngestSessionTelemetry(source, FakeStore(), 3, HALF_HOUR)(RACE_KEY, AFTER_2024)

    assert drivers_request(RACE_KEY).key not in source.fetched
