"""The assistant's data tools (ADR 0023). Each validates the model's input with its Pydantic
model, reads the clean model through the clean store, and returns each row as a citable block
whose source holds the row as read (ADR 0021). A result past its cap is cut and says how many
rows it left out."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationError

from f1_strategy.adapters.clean_store import PostgresRaceFacts, RaceHeader, RaceListing
from f1_strategy.application.assistant import Empty, Found, Rejected, ResultBlock, ToolSpec
from f1_strategy.domain.assistant import RowKey, RowSource, RowTable, RowValue, ToolName
from f1_strategy.domain.clean import CleanRow, DriverSession, SessionResult

FIRST_SEASON = 1950
RACE_NAME_MAX_CHARS = 100
DRIVER_COLUMNS = ("name_acronym", "full_name", "team_name")


class FindRacesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int | None = Field(default=None, ge=FIRST_SEASON)
    name: str | None = Field(default=None, min_length=1, max_length=RACE_NAME_MAX_CHARS)


class RaceResultsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_key: PositiveInt


class DriverStrategyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_key: PositiveInt
    driver_number: PositiveInt


class FindRaces:
    def __init__(self, facts: PostgresRaceFacts, max_rows: int) -> None:
        self._facts = facts
        self._max_rows = max_rows

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(ToolName.FIND_RACES, FindRacesInput.model_json_schema())

    async def run(self, arguments: Mapping[str, object]) -> Found | Empty | Rejected:
        request = _parse(FindRacesInput, arguments)
        if isinstance(request, Rejected):
            return request
        listings = await self._facts.races(request.year, request.name, self._max_rows)
        if not listings.races:
            return Empty("no race of the clean model matches")
        blocks = tuple(_block(_race_source(race)) for race in listings.races)
        return Found(blocks, listings.matches - len(blocks))


class RaceResults:
    def __init__(self, facts: PostgresRaceFacts, max_rows: int) -> None:
        self._facts = facts
        self._max_rows = max_rows

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(ToolName.RACE_RESULTS, RaceResultsInput.model_json_schema())

    async def run(self, arguments: Mapping[str, object]) -> Found | Empty | Rejected:
        request = _parse(RaceResultsInput, arguments)
        if isinstance(request, Rejected):
            return request
        classification = await self._facts.classification(request.session_key)
        if classification is None:
            return _not_loaded(request.session_key)
        rows = _Rows(classification.race, classification.drivers)
        sources = (
            *(rows.source(RowTable.SESSION_RESULT, result, ("driver_number",))
              for result in sorted(classification.results, key=_classified_order)),
            *(rows.source(RowTable.STARTING_GRID, slot, ("driver_number",))
              for slot in sorted(classification.starting_grid, key=lambda slot: slot.position)),
        )  # fmt: skip
        if not sources:
            return Empty(
                f"session_key {request.session_key} has no classification or starting grid"
            )
        return _capped(sources, self._max_rows)


class DriverStrategy:
    def __init__(self, facts: PostgresRaceFacts, max_rows: int) -> None:
        self._facts = facts
        self._max_rows = max_rows

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(ToolName.DRIVER_STRATEGY, DriverStrategyInput.model_json_schema())

    async def run(self, arguments: Mapping[str, object]) -> Found | Empty | Rejected:
        request = _parse(DriverStrategyInput, arguments)
        if isinstance(request, Rejected):
            return request
        session_key, driver_number = request.session_key, request.driver_number
        race = await self._facts.driver_race(session_key, driver_number)
        if race is None:
            return _not_loaded(session_key)
        if race.driver is None:
            return Rejected(
                f"driver_number {driver_number} did not take part in session_key {session_key}"
            )
        rows = _Rows(race.race, (race.driver,))
        sources = (
            *(rows.source(RowTable.STINT, stint, ("driver_number", "stint_number"))
              for stint in race.stints),
            *(rows.source(RowTable.PIT, pit, ("driver_number", "lap_number")) for pit in race.pits),
        )  # fmt: skip
        if not sources:
            return Empty(
                f"driver_number {driver_number} has no stints or pit stops"
                f" in session_key {session_key}"
            )
        return _capped(sources, self._max_rows)


class _Rows:
    """Row sources of one race, each with its driver's name and team. Every row read here has a
    foreign key to `driver_session`, so its driver is always there."""

    def __init__(self, race: RaceHeader, drivers: Sequence[DriverSession]) -> None:
        self._race = race
        self._drivers = {driver.driver_number: driver for driver in drivers}

    def source(self, table: RowTable, row: CleanRow, key_columns: tuple[str, ...]) -> RowSource:
        columns = asdict(row)
        driver = self._drivers[columns["driver_number"]]
        identity = {column: getattr(driver, column) for column in DRIVER_COLUMNS}
        skipped = {"session_key", *key_columns}
        return RowSource(
            table=table,
            session_key=self._race.session_key,
            meeting_name=self._race.meeting_name,
            year=self._race.year,
            key={column: columns[column] for column in key_columns},
            values=identity
            | {name: value for name, value in columns.items() if name not in skipped},
        )


def _race_source(race: RaceListing) -> RowSource:
    return RowSource(
        table=RowTable.SESSION,
        session_key=race.session_key,
        meeting_name=race.meeting_name,
        year=race.year,
        key={},
        values={
            "session_name": race.session_name,
            "date_start": race.date_start,
            "circuit_short_name": race.circuit_short_name,
            "country_name": race.country_name,
            "calibrated": race.calibrated,
        },
    )


def _classified_order(result: SessionResult) -> tuple[bool, int, int]:
    """Classified drivers by position, then the rest by number."""
    if result.position is None:
        return True, 0, result.driver_number
    return False, result.position, result.driver_number


def _capped(sources: Sequence[RowSource], max_rows: int) -> Found:
    kept = sources[:max_rows]
    return Found(tuple(_block(source) for source in kept), len(sources) - len(kept))


def _block(source: RowSource) -> ResultBlock:
    title = f"{source.meeting_name} {source.year}, {source.table}"
    key = ", ".join(f"{column} {value}" for column, value in source.key.items())
    text = "; ".join(f"{column}: {_shown(value)}" for column, value in source.values.items())
    return ResultBlock(source, f"{title} {key}" if key else title, text)


def _shown(value: RowValue | RowKey) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _not_loaded(session_key: int) -> Rejected:
    return Rejected(f"session_key {session_key} is not in the clean model")


def _parse[M: BaseModel](model: type[M], arguments: Mapping[str, object]) -> M | Rejected:
    try:
        return model.model_validate(arguments)
    except ValidationError as error:
        return Rejected(
            "; ".join(
                f"{'.'.join(str(part) for part in detail['loc'])}: {detail['msg']}"
                for detail in error.errors(include_url=False)
            )
        )
