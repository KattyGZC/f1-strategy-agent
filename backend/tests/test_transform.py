import asyncio
import copy
from collections.abc import AsyncIterator, Collection, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from f1_strategy.application import transform
from f1_strategy.application.transform import (
    ErrorKind,
    Load,
    Outcome,
    RunState,
    RunStatus,
    SeasonNotIngestedError,
    SessionOutcome,
    TransformPolicy,
    TransformReport,
    TransformSeason,
    TransientError,
    Version,
)
from f1_strategy.domain.clean import (
    TRANSFORM_VERSION,
    CleanDataError,
    clean_session,
    content_hash,
)
from f1_strategy.domain.openf1 import (
    Endpoint,
    JsonObject,
    Param,
    RawRequest,
    SessionType,
    meetings_request,
    season_cutoff,
    season_sessions_request,
)
from f1_strategy.domain.retry import RetryPolicy
from tests.samples import QUALIFYING, RACE, sample

RACE_KEY = int(RACE)
QUALIFYING_KEY = int(QUALIFYING)
NOW = datetime(2025, 2, 1, tzinfo=UTC)
FETCHED_AT = datetime(2024, 3, 3, tzinfo=UTC)
SETTLE = timedelta(hours=6)
CUTOFF = season_cutoff(2024, NOW, SETTLE)
INDEX = season_sessions_request(2024, CUTOFF)
CALENDAR = meetings_request(2024, CUTOFF)
RACE_AND_QUALIFYING = frozenset({SessionType.RACE, SessionType.QUALIFYING})
BACKOFF_BASE_S = 0.5


def request(endpoint: Endpoint, session_key: int) -> RawRequest:
    return RawRequest.of(endpoint, {Param.SESSION_KEY: session_key})


class FakeRaw:
    """The raw store after `make ingest YEAR=2024`, holding the two sampled sessions."""

    def __init__(self) -> None:
        self.documents: dict[str, tuple[list[JsonObject], datetime]] = {}
        sessions = {RACE_KEY: sample(RACE), QUALIFYING_KEY: sample(QUALIFYING)}
        self.put(INDEX, [data.session for data in sessions.values()])
        self.put(CALENDAR, [sessions[RACE_KEY].meeting])
        for key, data in sessions.items():
            for endpoint, rows in data.rows.items():
                self.put(request(endpoint, key), rows)

    def put(self, request: RawRequest, rows: list[JsonObject], at: datetime = FETCHED_AT) -> None:
        self.documents[request.key] = (rows, at)

    def rows_of(self, request: RawRequest) -> list[JsonObject]:
        return self.documents[request.key][0]

    def refetch(self, request: RawRequest) -> None:
        self.put(request, self.rows_of(request), FETCHED_AT + timedelta(days=1))

    async def rows(self, request: RawRequest) -> list[JsonObject] | None:
        stored = self.documents.get(request.key)
        return None if stored is None else copy.deepcopy(stored[0])

    async def fetched_at(self, requests: Sequence[RawRequest]) -> dict[str, datetime]:
        return {
            request.key: self.documents[request.key][1]
            for request in requests
            if request.key in self.documents
        }


@dataclass
class FakeClaim:
    state: RunState
    load: Load | None = None

    async def replace(self, load: Load) -> None:
        self.load = load


@dataclass
class FakeClean:
    """The clean store: a claim commits on a clean exit and rolls back on an exception."""

    states: dict[int, RunState] = field(default_factory=dict)
    loads: dict[int, Load] = field(default_factory=dict)
    held_elsewhere: set[int] = field(default_factory=set)
    commit_failures: dict[int, list[Exception]] = field(default_factory=dict)
    failures: dict[int, tuple[ErrorKind, str]] = field(default_factory=dict)
    replaced: list[int] = field(default_factory=list)
    claims: int = 0
    in_flight: int = 0
    max_in_flight: int = 0

    async def runs(self, session_keys: Collection[int]) -> dict[int, RunState]:
        return {key: self.states[key] for key in session_keys if key in self.states}

    @asynccontextmanager
    async def claim(
        self, session_key: int, version: Version, now: datetime
    ) -> AsyncIterator[FakeClaim | None]:
        self.claims += 1
        if session_key in self.held_elsewhere:
            yield None
            return
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)
            state = self.states.get(session_key) or RunState(RunStatus.PENDING, version, None, None)
            claim = FakeClaim(state)
            yield claim
            pending = self.commit_failures.get(session_key)
            if pending:
                raise pending.pop(0)
            if claim.load is not None:
                self.replaced.append(session_key)
                self.loads[session_key] = claim.load
                self.states[session_key] = RunState(
                    RunStatus.SUCCEEDED, version, None, claim.load.version
                )
        finally:
            self.in_flight -= 1

    async def record_waiting(self, session_key: int, version: Version, now: datetime) -> None:
        self.states[session_key] = RunState(
            RunStatus.WAITING_RAW, version, None, self._loaded(session_key)
        )

    async def record_failure(
        self, session_key: int, version: Version, kind: ErrorKind, message: str, now: datetime
    ) -> None:
        self.states[session_key] = RunState(
            RunStatus.FAILED, version, kind, self._loaded(session_key)
        )
        self.failures[session_key] = (kind, message)

    def _loaded(self, session_key: int) -> Version | None:
        state = self.states.get(session_key)
        return None if state is None else state.loaded


@dataclass
class Sleeps:
    calls: list[float] = field(default_factory=list)

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


async def run(
    raw: FakeRaw,
    clean: FakeClean,
    types: frozenset[SessionType] = RACE_AND_QUALIFYING,
    max_concurrency: int = 2,
    max_attempts: int = 3,
) -> TransformReport:
    return await sweep(raw, clean, max_concurrency, max_attempts)(2024, types, NOW)


def sweep(
    raw: FakeRaw,
    clean: FakeClean,
    max_concurrency: int = 2,
    max_attempts: int = 3,
    sleeps: Sleeps | None = None,
) -> TransformSeason:
    policy = TransformPolicy(max_concurrency, RetryPolicy(max_attempts, BACKOFF_BASE_S), SETTLE)
    return TransformSeason(raw, clean, policy, sleep=sleeps or Sleeps())


def outcomes(report: TransformReport) -> dict[int, Outcome]:
    return {session.session_key: session.outcome for session in report.outcomes}


def break_first_lap(raw: FakeRaw, session_key: int) -> None:
    raw.rows_of(request(Endpoint.LAPS, session_key))[0]["lap_number"] = "1"


@pytest.mark.anyio
async def test_a_first_sweep_loads_every_chosen_session() -> None:
    raw, clean = FakeRaw(), FakeClean()

    report = await run(raw, clean)

    assert outcomes(report) == {QUALIFYING_KEY: Outcome.LOADED, RACE_KEY: Outcome.LOADED}
    assert {key: state.status for key, state in clean.states.items()} == {
        QUALIFYING_KEY: RunStatus.SUCCEEDED,
        RACE_KEY: RunStatus.SUCCEEDED,
    }
    expected = clean_session(sample(RACE).raw())
    load = clean.loads[RACE_KEY]
    assert load.clean == expected
    assert load.output_hash == content_hash(expected)
    assert load.loaded_at == NOW
    assert load.version.transform_version == TRANSFORM_VERSION


@pytest.mark.anyio
async def test_a_second_sweep_over_the_same_raw_data_writes_nothing() -> None:
    raw, clean = FakeRaw(), FakeClean()
    await run(raw, clean)
    states, claims = dict(clean.states), clean.claims

    report = await run(raw, clean)

    assert set(outcomes(report).values()) == {Outcome.UNCHANGED}
    assert clean.claims == claims, "an unchanged session is not even claimed"
    assert sorted(clean.replaced) == [QUALIFYING_KEY, RACE_KEY]
    assert clean.states == states


@pytest.mark.anyio
async def test_a_refetched_document_reloads_only_its_session() -> None:
    raw, clean = FakeRaw(), FakeClean()
    await run(raw, clean)
    raw.refetch(request(Endpoint.LAPS, RACE_KEY))

    report = await run(raw, clean)

    assert outcomes(report) == {QUALIFYING_KEY: Outcome.UNCHANGED, RACE_KEY: Outcome.LOADED}


@pytest.mark.anyio
async def test_a_new_season_index_with_the_same_rows_reloads_nothing() -> None:
    raw, clean = FakeRaw(), FakeClean()
    await run(raw, clean)
    raw.refetch(INDEX)
    raw.refetch(CALENDAR)

    report = await run(raw, clean)

    assert set(outcomes(report).values()) == {Outcome.UNCHANGED}


@pytest.mark.anyio
async def test_a_new_transform_version_reloads_every_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, clean = FakeRaw(), FakeClean()
    await run(raw, clean)
    monkeypatch.setattr(transform, "TRANSFORM_VERSION", "2")

    report = await run(raw, clean)

    assert set(outcomes(report).values()) == {Outcome.LOADED}
    assert {load.version.transform_version for load in clean.loads.values()} == {"2"}


@pytest.mark.anyio
async def test_a_session_missing_raw_data_waits_and_the_others_load() -> None:
    raw, clean = FakeRaw(), FakeClean()
    del raw.documents[request(Endpoint.WEATHER, RACE_KEY).key]

    report = await run(raw, clean)

    assert outcomes(report) == {QUALIFYING_KEY: Outcome.LOADED, RACE_KEY: Outcome.WAITING_RAW}
    assert clean.states[RACE_KEY].status == RunStatus.WAITING_RAW
    assert RACE_KEY not in clean.loads


@pytest.mark.anyio
async def test_bad_data_fails_its_session_with_the_document_and_row() -> None:
    raw, clean = FakeRaw(), FakeClean()
    break_first_lap(raw, RACE_KEY)

    report = await run(raw, clean)

    message = "laps?session_key=9472: laps row 0: lap_number must be an integer, got '1'"
    assert outcomes(report) == {QUALIFYING_KEY: Outcome.LOADED, RACE_KEY: Outcome.FAILED}
    assert clean.failures[RACE_KEY] == (ErrorKind.PERMANENT, message)
    assert report.failures == (SessionOutcome(RACE_KEY, Outcome.FAILED, message),)


@pytest.mark.anyio
async def test_a_permanent_failure_is_not_retried_until_its_input_changes() -> None:
    raw, clean = FakeRaw(), FakeClean()
    break_first_lap(raw, RACE_KEY)
    await run(raw, clean)

    claims = clean.claims
    unchanged = await run(raw, clean)
    assert clean.claims == claims, "a session still failing is not even claimed"
    raw.rows_of(request(Endpoint.LAPS, RACE_KEY))[0]["lap_number"] = 1
    raw.refetch(request(Endpoint.LAPS, RACE_KEY))
    refetched = await run(raw, clean)

    assert outcomes(unchanged)[RACE_KEY] == Outcome.STILL_FAILING
    assert unchanged.count(Outcome.STILL_FAILING) == 1
    assert outcomes(refetched)[RACE_KEY] == Outcome.LOADED


@pytest.mark.anyio
async def test_a_transient_error_is_retried_with_backoff() -> None:
    raw = FakeRaw()
    clean = FakeClean(commit_failures={RACE_KEY: [TransientError("lost"), TransientError("lost")]})
    sleeps = Sleeps()

    report = await sweep(raw, clean, sleeps=sleeps)(2024, RACE_AND_QUALIFYING, NOW)

    assert outcomes(report)[RACE_KEY] == Outcome.LOADED
    assert sleeps.calls == [BACKOFF_BASE_S, 2 * BACKOFF_BASE_S]
    assert clean.replaced.count(RACE_KEY) == 1


@pytest.mark.anyio
async def test_a_transient_error_that_outlasts_the_retries_waits_for_the_next_sweep() -> None:
    raw = FakeRaw()
    clean = FakeClean(commit_failures={RACE_KEY: [TransientError("lost")] * 2})

    first = await run(raw, clean, max_attempts=2)
    second = await run(raw, clean, max_attempts=2)

    assert outcomes(first)[RACE_KEY] == Outcome.FAILED
    assert clean.failures[RACE_KEY] == (ErrorKind.TRANSIENT, "lost")
    assert outcomes(second)[RACE_KEY] == Outcome.LOADED


@pytest.mark.anyio
async def test_an_unexpected_error_fails_its_session_for_good() -> None:
    raw = FakeRaw()
    clean = FakeClean(commit_failures={RACE_KEY: [ValueError("violates lap_lap_number_check")]})

    report = await run(raw, clean)

    assert outcomes(report) == {QUALIFYING_KEY: Outcome.LOADED, RACE_KEY: Outcome.FAILED}
    assert clean.failures[RACE_KEY] == (
        ErrorKind.PERMANENT,
        "ValueError: violates lap_lap_number_check",
    )


@pytest.mark.anyio
async def test_a_session_held_by_another_worker_is_left_to_it() -> None:
    raw, clean = FakeRaw(), FakeClean(held_elsewhere={RACE_KEY})

    report = await run(raw, clean)

    assert outcomes(report) == {QUALIFYING_KEY: Outcome.LOADED, RACE_KEY: Outcome.BUSY}


@pytest.mark.anyio
async def test_a_session_another_worker_loaded_meanwhile_is_not_loaded_again() -> None:
    raw, clean = FakeRaw(), FakeClean()
    await run(raw, clean)

    class StaleRuns(FakeClean):
        async def runs(self, session_keys: Collection[int]) -> dict[int, RunState]:
            return {}  # read before the other worker committed

    stale = StaleRuns(states=dict(clean.states))
    report = await run(raw, stale)

    assert set(outcomes(report).values()) == {Outcome.UNCHANGED}
    assert stale.replaced == []


@pytest.mark.anyio
async def test_the_sweep_never_exceeds_its_concurrency() -> None:
    raw, clean = FakeRaw(), FakeClean()

    await run(raw, clean, max_concurrency=1)

    assert clean.max_in_flight == 1


@pytest.mark.anyio
async def test_only_the_chosen_session_types_are_transformed() -> None:
    raw, clean = FakeRaw(), FakeClean()

    report = await run(raw, clean, types=frozenset({SessionType.RACE}))

    assert outcomes(report) == {RACE_KEY: Outcome.LOADED}


@pytest.mark.anyio
@pytest.mark.parametrize("missing", [INDEX, CALENDAR], ids=["season index", "calendar"])
async def test_a_season_that_was_not_ingested_fails_the_sweep(missing: RawRequest) -> None:
    raw, clean = FakeRaw(), FakeClean()
    del raw.documents[missing.key]

    with pytest.raises(SeasonNotIngestedError) as error:
        await run(raw, clean)

    assert str(error.value).startswith(missing.key)


@pytest.mark.anyio
async def test_a_session_whose_meeting_is_not_in_the_calendar_fails() -> None:
    raw, clean = FakeRaw(), FakeClean()
    raw.rows_of(CALENDAR)[0]["meeting_key"] = 1

    report = await run(raw, clean)

    assert set(outcomes(report).values()) == {Outcome.FAILED}
    assert clean.failures[RACE_KEY] == (
        ErrorKind.PERMANENT,
        f"{CALENDAR.key}: meeting 1229 is not in it",
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("document", "field", "value", "message"),
    [
        pytest.param(
            INDEX,
            "session_name",
            "Shootout",
            f"{INDEX.key}: sessions: session_name 'Shootout' is not one of",
            id="season index",
        ),
        pytest.param(
            CALENDAR,
            "gmt_offset",
            "+3",
            f"{CALENDAR.key}: meetings: gmt_offset '+3' is not [-]HH:MM:SS",
            id="calendar",
        ),
    ],
)
async def test_bad_data_in_the_index_or_calendar_row_names_that_document(
    document: RawRequest, field: str, value: str, message: str
) -> None:
    raw, clean = FakeRaw(), FakeClean()
    raw.rows_of(document)[0][field] = value

    await run(raw, clean)

    assert clean.failures[RACE_KEY][1].startswith(message)


@pytest.mark.anyio
async def test_a_document_that_disappears_while_read_is_a_transient_error() -> None:
    weather = request(Endpoint.WEATHER, RACE_KEY)

    class Vanishing(FakeRaw):
        async def rows(self, request: RawRequest) -> list[JsonObject] | None:
            return None if request.key == weather.key else await super().rows(request)

    clean = FakeClean()
    report = await run(Vanishing(), clean, max_attempts=1)

    assert outcomes(report)[RACE_KEY] == Outcome.FAILED
    assert clean.failures[RACE_KEY] == (
        ErrorKind.TRANSIENT,
        "weather?session_key=9472 disappeared while the session was read",
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(
            {"session_key": "9472"},
            "sessions row 2: session_key must be an integer, got '9472'",
            id="text key",
        ),
        pytest.param(
            {"location": "Bahrain"},
            "sessions row 2: two different rows for session_key 9472",
            id="one key, two rows",
        ),
    ],
)
async def test_a_broken_season_index_fails_the_sweep(change: JsonObject, message: str) -> None:
    raw, clean = FakeRaw(), FakeClean()
    index = raw.rows_of(INDEX)
    index.append({**index[0], **change})

    with pytest.raises(CleanDataError) as error:
        await run(raw, clean)

    assert str(error.value) == message


@pytest.mark.anyio
async def test_an_identical_row_twice_in_the_index_is_one_session() -> None:
    raw, clean = FakeRaw(), FakeClean()
    index = raw.rows_of(INDEX)
    index.append(dict(index[0]))

    report = await run(raw, clean)

    assert outcomes(report) == {QUALIFYING_KEY: Outcome.LOADED, RACE_KEY: Outcome.LOADED}


def test_the_policy_needs_at_least_one_worker() -> None:
    with pytest.raises(ValueError, match="max_concurrency must be at least 1"):
        TransformPolicy(0, RetryPolicy(1, 1.0), SETTLE)
