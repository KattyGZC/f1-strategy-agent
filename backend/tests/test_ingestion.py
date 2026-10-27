import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from f1_strategy.application.ingestion import (
    IngestionReport,
    IngestSeason,
    IngestSessionTelemetry,
    SessionNotFoundError,
    SessionNotSettledError,
)
from f1_strategy.domain.openf1 import (
    Endpoint,
    JsonObject,
    Param,
    RawRequest,
    RawResponse,
    SessionType,
    drivers_request,
    meetings_request,
    session_request,
)
from tests.factories import (
    CANCELLED_KEY,
    DRIVERS,
    PRACTICE_KEY,
    QUALIFYING_KEY,
    RACE_END,
    RACE_KEY,
    SEASON_2024,
    SEASON_2024_SETTLED,
    session_row,
)

FETCHED_AT = datetime(2026, 10, 26, tzinfo=UTC)
RACE_AND_QUALIFYING = frozenset({SessionType.RACE, SessionType.QUALIFYING})
RACE_ENDPOINT_COUNT = 11
QUALIFYING_ENDPOINT_COUNT = 10
HALF_HOUR = timedelta(minutes=30)
SETTLE = timedelta(hours=6)


class SourceFailedError(Exception):
    pass


class FakeSource:
    def __init__(
        self,
        payloads: dict[str, list[JsonObject]],
        failing: frozenset[str] = frozenset(),
        season_index: list[JsonObject] | None = None,
    ) -> None:
        self._payloads = payloads
        self._failing = failing
        self._season_index = season_index or []
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
        return RawResponse(request, self._payload(request), FETCHED_AT)

    def _payload(self, request: RawRequest) -> list[JsonObject]:
        if request.endpoint == Endpoint.SESSIONS and Param.YEAR in dict(request.params):
            return self._season_index
        return self._payloads.get(request.key, [])


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
    return FakeSource({}, failing, season_index=SEASON_2024)


def season(source: FakeSource, store: FakeStore, max_concurrency: int = 3) -> IngestSeason:
    return IngestSeason(source, store, max_concurrency, SETTLE)


def telemetry(source: FakeSource, store: FakeStore) -> IngestSessionTelemetry:
    return IngestSessionTelemetry(source, store, 3, SETTLE, HALF_HOUR)


@pytest.mark.anyio
async def test_season_stores_the_index_and_every_endpoint_of_the_chosen_sessions() -> None:
    source, store = season_source(), FakeStore()

    report = await season(source, store, max_concurrency=3)(
        2024, RACE_AND_QUALIFYING, SEASON_2024_SETTLED
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

    await season(source, store, max_concurrency=3)(2024, RACE_AND_QUALIFYING, SEASON_2024_SETTLED)

    stored_session_keys = {response.request.session_key for response in store.responses.values()}
    assert stored_session_keys == {None, RACE_KEY, QUALIFYING_KEY}
    assert PRACTICE_KEY not in stored_session_keys
    assert CANCELLED_KEY not in stored_session_keys


@pytest.mark.anyio
async def test_a_second_season_run_fetches_nothing() -> None:
    store = FakeStore()
    await season(season_source(), store, max_concurrency=3)(
        2024, RACE_AND_QUALIFYING, SEASON_2024_SETTLED
    )
    second_source = season_source()

    report = await season(second_source, store, max_concurrency=3)(
        2024, RACE_AND_QUALIFYING, SEASON_2024_SETTLED
    )

    assert second_source.fetched == []
    assert report.fetched == 0
    assert report.already_stored == report.requests == 2 + 21


@pytest.mark.anyio
async def test_a_failed_request_stops_the_run_with_its_own_error_and_a_rerun_resumes() -> None:
    store = FakeStore()
    failing = frozenset({"laps?session_key=9472"})

    with pytest.raises(SourceFailedError, match=r"laps\?session_key=9472"):
        await season(season_source(failing), store, max_concurrency=1)(
            2024, RACE_AND_QUALIFYING, SEASON_2024_SETTLED
        )

    assert "laps?session_key=9472" not in store.responses
    stored_before_resume = set(store.responses)
    resumed_source = season_source()
    report = await season(resumed_source, store, max_concurrency=3)(
        2024, RACE_AND_QUALIFYING, SEASON_2024_SETTLED
    )
    assert "laps?session_key=9472" in resumed_source.fetched
    assert stored_before_resume.isdisjoint(resumed_source.fetched)
    assert report.fetched == len(resumed_source.fetched)


@pytest.mark.anyio
async def test_season_never_exceeds_the_concurrency_bound() -> None:
    source = season_source()

    await season(source, FakeStore(), max_concurrency=2)(
        2024, RACE_AND_QUALIFYING, SEASON_2024_SETTLED
    )

    assert source.max_in_flight == 2


@pytest.mark.anyio
async def test_a_season_in_progress_ingests_only_sessions_that_have_settled() -> None:
    source, store = season_source(), FakeStore()
    race_morning = datetime(2024, 3, 2, 10, 30, tzinfo=UTC)

    report = await season(source, store)(2024, RACE_AND_QUALIFYING, race_morning)

    assert report.sessions == 1
    assert "sessions?date_end<2024-03-02T04%3A00%3A00%2B00%3A00&year=2024" in store.responses
    assert {response.request.session_key for response in store.responses.values()} == {
        None,
        QUALIFYING_KEY,
    }


@pytest.mark.anyio
async def test_a_later_run_of_a_season_in_progress_adds_what_settled_since() -> None:
    store = FakeStore()
    await season(season_source(), store)(2024, RACE_AND_QUALIFYING, RACE_END)
    after_settling = RACE_END + SETTLE + timedelta(hours=1)
    later_source = season_source()

    report = await season(later_source, store)(2024, RACE_AND_QUALIFYING, after_settling)

    assert report.sessions == 2
    assert later_source.fetched[0] == (
        "sessions?date_end<2024-03-02T18%3A00%3A00%2B00%3A00&year=2024"
    )
    assert report.fetched == 1 + RACE_ENDPOINT_COUNT
    assert all("9468" not in key for key in later_source.fetched)


@pytest.mark.anyio
async def test_a_finished_season_reuses_one_index_whenever_it_runs() -> None:
    store = FakeStore()
    await season(season_source(), store)(
        2024, RACE_AND_QUALIFYING, datetime(2025, 2, 1, tzinfo=UTC)
    )
    years_later_source = season_source()

    report = await season(years_later_source, store)(
        2024, RACE_AND_QUALIFYING, datetime(2031, 6, 1, tzinfo=UTC)
    )

    assert years_later_source.fetched == []
    assert report.fetched == 0


def test_concurrency_must_be_at_least_one() -> None:
    use_case = season(season_source(), FakeStore(), max_concurrency=0)

    with pytest.raises(ValueError, match="max_concurrency must be at least 1, got 0"):
        asyncio.run(use_case(2024, RACE_AND_QUALIFYING, SEASON_2024_SETTLED))


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

    report = await telemetry(source, store)(RACE_KEY, SEASON_2024_SETTLED)

    windows = 2 * 2 * 4
    assert report == IngestionReport(sessions=1, requests=2 + windows, fetched=2 + windows)
    car_data_keys = [key for key in store.responses if key.startswith("car_data?")]
    location_keys = [key for key in store.responses if key.startswith("location?")]
    assert len(car_data_keys) == len(location_keys) == 2 * 4


@pytest.mark.anyio
async def test_telemetry_reuses_a_stored_driver_list() -> None:
    store = FakeStore()
    await store.put(RawResponse(drivers_request(RACE_KEY), DRIVERS, FETCHED_AT))
    source = telemetry_source([session_row(RACE_KEY, "Race")])

    await telemetry(source, store)(RACE_KEY, SEASON_2024_SETTLED)

    assert drivers_request(RACE_KEY).key not in source.fetched


@pytest.mark.anyio
async def test_telemetry_of_a_session_that_has_not_settled_is_refused() -> None:
    source = telemetry_source([session_row(RACE_KEY, "Race")])
    just_before_settling = RACE_END + SETTLE - timedelta(seconds=1)

    with pytest.raises(
        SessionNotSettledError,
        match=r"session 9472 ends at 2024-03-02T17:00:00\+00:00; "
        r"it can be ingested from 2024-03-02T23:00:00\+00:00",
    ):
        await telemetry(source, FakeStore())(RACE_KEY, just_before_settling)

    assert source.fetched == [session_request(RACE_KEY).key]


@pytest.mark.parametrize("session_rows", [[], [session_row(RACE_KEY, "Race")] * 2])
@pytest.mark.anyio
async def test_telemetry_needs_exactly_one_session(session_rows: list[JsonObject]) -> None:
    source = telemetry_source(session_rows)

    with pytest.raises(SessionNotFoundError, match=f"returned {len(session_rows)}"):
        await telemetry(source, FakeStore())(RACE_KEY, SEASON_2024_SETTLED)

    assert drivers_request(RACE_KEY).key not in source.fetched
