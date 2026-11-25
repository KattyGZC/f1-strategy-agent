from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from psycopg import errors

from f1_strategy.adapters.assistant_suggestions import SuggestionId
from f1_strategy.adapters.assistant_tools import (
    DeclineQuestion,
    DriverStrategy,
    FindRaces,
    RaceResults,
)
from f1_strategy.adapters.clean_store import (
    Pool,
    PostgresCalibrationStore,
    PostgresCleanStore,
    PostgresRaceFacts,
    connection_pool,
    read_only,
)
from f1_strategy.adapters.migrate import upgrade
from f1_strategy.application.assistant import (
    Declined,
    Empty,
    Found,
    Rejected,
    ResultBlock,
    ToolFailedError,
)
from f1_strategy.application.calibration import Fingerprint
from f1_strategy.application.transform import Load, Version
from f1_strategy.domain.assistant import (
    DeclineReason,
    RowKey,
    RowSource,
    RowTable,
    RowValue,
    ToolName,
)
from f1_strategy.domain.clean import (
    CleanRow,
    CleanSession,
    Compound,
    SessionResult,
    StartingGrid,
    clean_session,
    content_hash,
)
from f1_strategy.domain.lap_time_model import CALIBRATION_VERSION, Calibration
from f1_strategy.domain.openf1 import SessionName
from tests.postgres import CONNECT_TIMEOUT_S, fresh_database
from tests.samples import QUALIFYING, RACE, sample

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)
RACE_KEY = int(RACE)
BAHRAIN = clean_session(sample(RACE).raw())
MAX_ROWS = 60
GRID = (
    StartingGrid(RACE_KEY, 1, 1, Decimal("89.179")),
    StartingGrid(RACE_KEY, 16, 2, Decimal("89.407")),
    StartingGrid(RACE_KEY, 11, 5, Decimal("89.537")),
    StartingGrid(RACE_KEY, 55, 4, Decimal("89.505")),
)
DRIVERS: dict[int, dict[str, RowValue]] = {
    1: {"name_acronym": "VER", "full_name": "Max VERSTAPPEN", "team_name": "Red Bull Racing"},
    11: {"name_acronym": "PER", "full_name": "Sergio PEREZ", "team_name": "Red Bull Racing"},
    16: {"name_acronym": "LEC", "full_name": "Charles LECLERC", "team_name": "Ferrari"},
    55: {"name_acronym": "SAI", "full_name": "Carlos SAINZ", "team_name": "Ferrari"},
}


def as_session(session: CleanSession, session_key: int, after: timedelta) -> CleanSession:
    """The same race under another key, later by `after`."""

    def moved[T: CleanRow](rows: tuple[T, ...]) -> tuple[T, ...]:
        return tuple(replace(row, session_key=session_key) for row in rows)

    race = replace(
        session.session,
        session_key=session_key,
        date_start=session.session.date_start + after,
        date_end=session.session.date_end + after,
    )
    return replace(
        session,
        session=race,
        drivers=moved(session.drivers),
        laps=moved(session.laps),
        stints=moved(session.stints),
        pits=moved(session.pits),
        intervals=moved(session.intervals),
        positions=moved(session.positions),
        race_control=moved(session.race_control),
        weather=moved(session.weather),
        results=moved(session.results),
        qualifying_phases=moved(session.qualifying_phases),
        starting_grid=moved(session.starting_grid),
        overtakes=moved(session.overtakes),
        team_radio=moved(session.team_radio),
    )


@pytest.fixture
def postgres_uri(postgres_server_uri: str) -> str:
    uri = fresh_database(postgres_server_uri)
    upgrade(uri, CONNECT_TIMEOUT_S)
    return uri


@pytest.fixture
async def pool(postgres_uri: str) -> AsyncIterator[Pool]:
    pool: Pool = connection_pool(postgres_uri, max_size=2, connect_timeout_s=CONNECT_TIMEOUT_S)
    async with pool:
        yield pool


async def load(pool: Pool, session: CleanSession) -> None:
    version = Version("input", "1")
    async with PostgresCleanStore(pool).claim(session.session.session_key, version, NOW) as claim:
        assert claim is not None
        await claim.replace(Load(session, version, content_hash(session), NOW))


@pytest.fixture
async def facts(pool: Pool) -> PostgresRaceFacts:
    await load(pool, replace(BAHRAIN, starting_grid=GRID))
    await load(pool, clean_session(sample(QUALIFYING).raw()))
    return PostgresRaceFacts(pool)


def session_row(session_key: int, date_start: datetime, *, calibrated: bool) -> RowSource:
    return RowSource(
        table=RowTable.SESSION,
        session_key=session_key,
        meeting_name="Bahrain Grand Prix",
        year=2024,
        key={},
        values={
            "session_name": SessionName.GRAND_PRIX,
            "date_start": date_start,
            "circuit_short_name": "Sakhir",
            "country_name": "Bahrain",
            "calibrated": calibrated,
        },
    )


def block(source: RowSource) -> ResultBlock:
    key = ", ".join(f"{name} {value}" for name, value in source.key.items())
    title = f"{source.meeting_name} {source.year}, {source.table}"
    return ResultBlock(source, f"{title} {key}" if key else title, text(source))


def text(source: RowSource) -> str:
    def shown(value: object) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    return "; ".join(f"{name}: {shown(value)}" for name, value in source.values.items())


def bahrain_row(
    table: RowTable, key: Mapping[str, RowKey], values: Mapping[str, RowValue]
) -> RowSource:
    return RowSource(table, RACE_KEY, "Bahrain Grand Prix", 2024, key, values)


def result_row(result: SessionResult) -> RowSource:
    return bahrain_row(
        RowTable.SESSION_RESULT,
        {"driver_number": result.driver_number},
        {
            **DRIVERS[result.driver_number],
            "position": result.position,
            "number_of_laps": result.number_of_laps,
            "dnf": result.dnf,
            "dns": result.dns,
            "dsq": result.dsq,
            "duration": result.duration,
            "gap_to_leader_s": result.gap_to_leader_s,
            "gap_to_leader_laps": result.gap_to_leader_laps,
            "points": result.points,
        },
    )


def grid_row(grid: StartingGrid) -> RowSource:
    return bahrain_row(
        RowTable.STARTING_GRID,
        {"driver_number": grid.driver_number},
        {
            **DRIVERS[grid.driver_number],
            "position": grid.position,
            "lap_duration": grid.lap_duration,
        },
    )


def test_each_tool_offers_the_json_schema_of_its_input() -> None:
    facts = PostgresRaceFacts(connection_pool("postgresql://localhost/unused", 1, 1))
    tools = (FindRaces(facts, MAX_ROWS), RaceResults(facts, MAX_ROWS), DriverStrategy(facts, 1))

    assert [(tool.spec.name, tool.spec.input_schema.get("required")) for tool in tools] == [
        (ToolName.FIND_RACES, None),
        (ToolName.RACE_RESULTS, ["session_key"]),
        (ToolName.DRIVER_STRATEGY, ["session_key", "driver_number"]),
    ]


@pytest.mark.anyio
async def test_find_races_lists_the_races_of_a_year_and_whether_each_is_calibrated(
    pool: Pool, facts: PostgresRaceFacts
) -> None:
    later = as_session(BAHRAIN, 9480, timedelta(days=7))
    await load(pool, later)
    calibration = Calibration(
        race_laps=57,
        compounds=(),
        drivers=(),
        residual_rmse_s=Decimal(0),
        exclusions=(),
        track_temperature=None,
        rain_readings=0,
        pit_loss=None,
        pit_stop_exclusions=(),
    )
    fingerprint = Fingerprint(content_hash(later), CALIBRATION_VERSION)
    await PostgresCalibrationStore(pool).save(9480, fingerprint, calibration, NOW)

    result = await FindRaces(facts, MAX_ROWS).run({"year": 2024})

    assert result == Found(
        (
            block(session_row(RACE_KEY, BAHRAIN.session.date_start, calibrated=False)),
            block(session_row(9480, later.session.date_start, calibrated=True)),
        ),
        omitted_rows=0,
    )


@pytest.mark.parametrize("name", ["bahrain grand", "SAKHIR", "Bahrain"])
@pytest.mark.anyio
async def test_find_races_matches_a_name_in_the_meeting_circuit_or_country_ignoring_case(
    facts: PostgresRaceFacts, name: str
) -> None:
    result = await FindRaces(facts, MAX_ROWS).run({"name": name})

    assert result == Found(
        (block(session_row(RACE_KEY, BAHRAIN.session.date_start, calibrated=False)),), 0
    )


@pytest.mark.anyio
async def test_find_races_keeps_the_earliest_races_up_to_its_cap_and_counts_the_rest(
    pool: Pool, facts: PostgresRaceFacts
) -> None:
    for week in (1, 2):
        await load(pool, as_session(BAHRAIN, 9480 + week, timedelta(days=7 * week)))

    result = await FindRaces(facts, max_rows=1).run({})

    assert result == Found(
        (block(session_row(RACE_KEY, BAHRAIN.session.date_start, calibrated=False)),), 2
    )


@pytest.mark.parametrize("arguments", [{"year": 2023}, {"name": "Monza"}])
@pytest.mark.anyio
async def test_find_races_says_so_when_no_race_matches(
    facts: PostgresRaceFacts, arguments: dict[str, object]
) -> None:
    assert await FindRaces(facts, MAX_ROWS).run(arguments) == Empty(
        "no race of the clean model matches"
    )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        pytest.param(
            {"year": 1949}, "year: Input should be greater than or equal to 1950", id="year"
        ),
        pytest.param({"name": ""}, "name: String should have at least 1 character", id="empty"),
        pytest.param(
            {"name": "x" * 101}, "name: String should have at most 100 characters", id="long"
        ),
        pytest.param({"season": 2024}, "season: Extra inputs are not permitted", id="extra"),
    ],
)
@pytest.mark.anyio
async def test_find_races_rejects_an_invalid_input_naming_the_field(
    facts: PostgresRaceFacts, arguments: dict[str, object], message: str
) -> None:
    assert await FindRaces(facts, MAX_ROWS).run(arguments) == Rejected(message)


@pytest.mark.anyio
async def test_race_results_give_the_classification_by_position_then_the_grid(
    facts: PostgresRaceFacts,
) -> None:
    result = await RaceResults(facts, MAX_ROWS).run({"session_key": RACE_KEY})

    by_driver = {row.driver_number: row for row in BAHRAIN.results}
    assert result == Found(
        (
            *(block(result_row(by_driver[driver])) for driver in (1, 11, 55, 16)),
            *(block(grid_row(row)) for row in sorted(GRID, key=lambda row: row.position)),
        ),
        omitted_rows=0,
    )


@pytest.mark.anyio
async def test_race_results_put_unclassified_drivers_last_by_number(pool: Pool) -> None:
    results = tuple(
        replace(row, position=None, dnf=True) if row.driver_number in {1, 11} else row
        for row in BAHRAIN.results
    )
    await load(pool, replace(BAHRAIN, results=results))

    result = await RaceResults(PostgresRaceFacts(pool), MAX_ROWS).run({"session_key": RACE_KEY})

    assert isinstance(result, Found)
    assert [block.source.key["driver_number"] for block in result.blocks] == [55, 16, 1, 11]


@pytest.mark.anyio
async def test_race_results_are_cut_at_the_cap(facts: PostgresRaceFacts) -> None:
    result = await RaceResults(facts, max_rows=3).run({"session_key": RACE_KEY})

    assert isinstance(result, Found)
    assert (len(result.blocks), result.omitted_rows) == (3, 5)


@pytest.mark.anyio
async def test_race_results_of_a_session_without_them_say_so(pool: Pool) -> None:
    await load(pool, replace(BAHRAIN, results=(), starting_grid=()))

    result = await RaceResults(PostgresRaceFacts(pool), MAX_ROWS).run({"session_key": RACE_KEY})

    assert result == Empty("session_key 9472 has no classification or starting grid")


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        pytest.param(
            {"session_key": 9999}, "session_key 9999 is not in the clean model", id="unknown"
        ),
        pytest.param({"session_key": 0}, "session_key: Input should be greater than 0", id="zero"),
        pytest.param({}, "session_key: Field required", id="missing"),
    ],
)
@pytest.mark.anyio
async def test_race_results_reject_a_session_the_clean_model_lacks(
    facts: PostgresRaceFacts, arguments: dict[str, object], message: str
) -> None:
    assert await RaceResults(facts, MAX_ROWS).run(arguments) == Rejected(message)


@pytest.mark.anyio
async def test_driver_strategy_gives_the_driver_stints_then_pit_stops(
    facts: PostgresRaceFacts,
) -> None:
    result = await DriverStrategy(facts, MAX_ROWS).run(
        {"session_key": RACE_KEY, "driver_number": 1}
    )

    stints = [
        (1, Compound.SOFT, 1, 17, 3),
        (2, Compound.HARD, 18, 37, 0),
        (3, Compound.SOFT, 38, 57, 0),
    ]
    pits = [pit for pit in BAHRAIN.pits if pit.driver_number == 1]
    assert result == Found(
        (
            *(
                block(
                    bahrain_row(
                        RowTable.STINT,
                        {"driver_number": 1, "stint_number": number},
                        {
                            **DRIVERS[1],
                            "compound": compound,
                            "lap_start": lap_start,
                            "lap_end": lap_end,
                            "tyre_age_at_start": tyre_age,
                        },
                    )
                )
                for number, compound, lap_start, lap_end, tyre_age in stints
            ),
            *(
                block(
                    bahrain_row(
                        RowTable.PIT,
                        {"driver_number": 1, "lap_number": pit.lap_number},
                        {
                            **DRIVERS[1],
                            "date": pit.date,
                            "lane_duration": pit.lane_duration,
                            "stop_duration": pit.stop_duration,
                        },
                    )
                )
                for pit in pits
            ),
        ),
        omitted_rows=0,
    )


@pytest.mark.anyio
async def test_driver_strategy_of_a_driver_without_stints_or_stops_says_so(pool: Pool) -> None:
    await load(
        pool,
        replace(
            BAHRAIN,
            stints=tuple(row for row in BAHRAIN.stints if row.driver_number != 16),
            pits=tuple(row for row in BAHRAIN.pits if row.driver_number != 16),
        ),
    )

    result = await DriverStrategy(PostgresRaceFacts(pool), MAX_ROWS).run(
        {"session_key": RACE_KEY, "driver_number": 16}
    )

    assert result == Empty("driver_number 16 has no stints or pit stops in session_key 9472")


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        pytest.param(
            {"session_key": RACE_KEY, "driver_number": 44},
            "driver_number 44 did not take part in session_key 9472",
            id="driver",
        ),
        pytest.param(
            {"session_key": 9999, "driver_number": 1},
            "session_key 9999 is not in the clean model",
            id="session",
        ),
        pytest.param(
            {"session_key": RACE_KEY, "driver_number": "one"},
            "driver_number: Input should be a valid integer, unable to parse string as an integer",
            id="type",
        ),
    ],
)
@pytest.mark.anyio
async def test_driver_strategy_rejects_ids_the_clean_model_lacks(
    facts: PostgresRaceFacts, arguments: dict[str, object], message: str
) -> None:
    assert await DriverStrategy(facts, MAX_ROWS).run(arguments) == Rejected(message)


@pytest.mark.anyio
async def test_a_tool_whose_store_is_unreachable_fails(postgres_uri: str) -> None:
    pool: Pool = connection_pool(postgres_uri, max_size=1, connect_timeout_s=CONNECT_TIMEOUT_S)

    with pytest.raises(ToolFailedError, match="PoolClosed"):
        await RaceResults(PostgresRaceFacts(pool), MAX_ROWS).run({"session_key": RACE_KEY})


@pytest.mark.usefixtures("facts")
@pytest.mark.anyio
async def test_a_write_inside_the_read_only_transaction_is_refused(pool: Pool) -> None:
    async with read_only(pool) as connection:
        with pytest.raises(errors.ReadOnlySqlTransaction):
            await connection.execute("DELETE FROM session WHERE session_key = %s", [RACE_KEY])


@pytest.mark.anyio
async def test_declining_names_its_reason_and_one_of_our_suggestions() -> None:
    result = await DeclineQuestion().run(
        {"reason": "future_race", "suggestion_id": SuggestionId.NORRIS_MONZA_STOPS}
    )

    assert result == Declined(DeclineReason.FUTURE_RACE, SuggestionId.NORRIS_MONZA_STOPS)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        pytest.param(
            {"reason": "future_race", "suggestion_id": "who_wins_next"},
            "suggestion_id: Input should be 'norris_monza_stops', 'silverstone_winner',"
            " 'leclerc_monza_two_stops' or 'two_compounds_rule'",
            id="suggestion",
        ),
        pytest.param(
            {"reason": "boring", "suggestion_id": "silverstone_winner"},
            "reason: Input should be 'future_race', 'live_data', 'season_not_loaded',"
            " 'not_formula_1' or 'other'",
            id="reason",
        ),
    ],
)
@pytest.mark.anyio
async def test_a_decline_outside_our_reasons_or_suggestions_is_rejected(
    arguments: dict[str, object], message: str
) -> None:
    assert await DeclineQuestion().run(arguments) == Rejected(message)


def test_the_decline_offers_the_json_schema_of_its_input() -> None:
    spec = DeclineQuestion().spec

    assert (spec.name, spec.input_schema.get("required")) == (
        ToolName.DECLINE_QUESTION,
        ["reason", "suggestion_id"],
    )
