"""The assistant's answer as a stream of typed events, and the sources it cites (ADR 0023).

A source holds what a tool returned in this answer, so opening a citation needs no other request.
Only a source recorded in the answer's ledger can be cited (ADR 0021).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class ToolName(StrEnum):
    FIND_RACES = "find_races"
    RACE_RESULTS = "race_results"
    DRIVER_STRATEGY = "driver_strategy"
    LAP_TIMES = "lap_times"
    RACE_CONTROL = "race_control"
    WEATHER = "weather"
    SEARCH_RULES = "search_rules"
    SIMULATE_STRATEGIES = "simulate_strategies"
    DECLINE_QUESTION = "decline_question"


class AnswerEventKind(StrEnum):
    STEP = "step"
    TEXT = "text"
    CITATION = "citation"
    DECLINED = "declined"
    DONE = "done"
    ERROR = "error"


class StepStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    EMPTY = "empty"
    REJECTED = "rejected"
    FAILED = "failed"


class DeclineReason(StrEnum):
    FUTURE_RACE = "future_race"
    LIVE_DATA = "live_data"
    SEASON_NOT_LOADED = "season_not_loaded"
    NOT_FORMULA_1 = "not_formula_1"
    OTHER = "other"


class AnswerOutcome(StrEnum):
    ANSWERED = "answered"
    DECLINED = "declined"


class AnswerError(StrEnum):
    """Why an answer ended early; each is also a value of the API's `ErrorCode`."""

    ANSWER_TIMEOUT = "answer_timeout"
    TOOL_ROUNDS_EXCEEDED = "tool_rounds_exceeded"
    ANSWER_TOO_LONG = "answer_too_long"
    ASSISTANT_PAUSED = "assistant_paused"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_REFUSED = "model_refused"
    INTERNAL_ERROR = "internal_error"


class RowTable(StrEnum):
    SESSION = "session"
    SESSION_RESULT = "session_result"
    STARTING_GRID = "starting_grid"
    STINT = "stint"
    PIT = "pit"
    LAP = "lap"
    RACE_CONTROL = "race_control"
    WEATHER = "weather"


type RowKey = int | datetime
type RowValue = str | int | float | Decimal | bool | datetime | None


@dataclass(frozen=True)
class RowSource:
    """`key` holds the row's primary key after `session_key`, in the table's column order."""

    table: RowTable
    session_key: int
    meeting_name: str
    year: int
    key: Mapping[str, RowKey]
    values: Mapping[str, RowValue]


type Source = RowSource


@dataclass(frozen=True)
class StepEvent:
    step: int
    tool: ToolName
    status: StepStatus


@dataclass(frozen=True)
class TextEvent:
    delta: str


@dataclass(frozen=True)
class CitationEvent:
    """`source` is sent the first time its number appears, and None after."""

    number: int
    source: Source | None


@dataclass(frozen=True)
class DeclinedEvent:
    reason: DeclineReason
    suggestion_id: str


@dataclass(frozen=True)
class DoneEvent:
    outcome: AnswerOutcome


@dataclass(frozen=True)
class ErrorEvent:
    code: AnswerError


type AnswerEvent = StepEvent | TextEvent | CitationEvent | DeclinedEvent | DoneEvent | ErrorEvent


def source_id(source: Source) -> str:
    """The id a tool result block carries, and the model's citations name."""
    parts = (str(source.session_key), *(_key_part(value) for value in source.key.values()))
    return ":".join(("row", source.table, *parts))


def _key_part(value: RowKey) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


class CitationLedger:
    """The sources the tools returned in one answer, and the numbers they are cited by."""

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}
        self._numbers: dict[str, int] = {}

    def record(self, source: Source) -> None:
        self._sources.setdefault(source_id(source), source)

    def cite(self, cited_id: str) -> CitationEvent | None:
        """None when no tool returned the source in this answer."""
        source = self._sources.get(cited_id)
        if source is None:
            return None
        number = self._numbers.get(cited_id)
        if number is not None:
            return CitationEvent(number, None)
        number = len(self._numbers) + 1
        self._numbers[cited_id] = number
        return CitationEvent(number, source)
