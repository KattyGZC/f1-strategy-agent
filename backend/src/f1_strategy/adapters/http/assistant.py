"""The assistant's routes: its status, and one question answered as a stream of typed events
(ADR 0023)."""

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field, StringConstraints

from f1_strategy.adapters.assistant_suggestions import SUGGESTIONS, SuggestionId
from f1_strategy.adapters.http.errors import ERROR_CODE_STATE, INTERNAL_ERROR_DETAIL, request_id
from f1_strategy.adapters.http.responses import ErrorCode, ErrorResponse, Responses
from f1_strategy.adapters.http.services import (
    AssistantAvailable,
    AssistantDisabledError,
    Services,
)
from f1_strategy.adapters.observability import log_fields
from f1_strategy.domain.assistant import (
    AnswerError,
    AnswerEvent,
    AnswerEventKind,
    AnswerOutcome,
    CitationEvent,
    DeclinedEvent,
    DeclineReason,
    DoneEvent,
    ErrorEvent,
    RowSource,
    RowTable,
    RowValue,
    SourceKind,
    StepEvent,
    StepStatus,
    TextEvent,
    ToolName,
)

# An answer's events wait here while the browser reads; the answer's limits bound how many
# it sends.
ANSWER_EVENT_BUFFER = 64

ANSWER_ERROR_DETAILS = {
    AnswerError.ANSWER_TIMEOUT: "the answer took longer than its time limit",
    AnswerError.TOOL_ROUNDS_EXCEEDED: "the answer needed more tool rounds than it may use",
    AnswerError.ANSWER_TOO_LONG: "the answer grew past its length limit",
    AnswerError.ASSISTANT_PAUSED: "the assistant is paused until its budget resets",
    AnswerError.MODEL_UNAVAILABLE: "the language model is unavailable; try again later",
    AnswerError.MODEL_REFUSED: "the language model declined to answer",
    AnswerError.INTERNAL_ERROR: INTERNAL_ERROR_DETAIL,
}

logger = logging.getLogger("f1_strategy.http")

router = APIRouter(tags=["assistant"])


class AssistantState(StrEnum):
    AVAILABLE = "available"
    PAUSED = "paused"
    DISABLED = "disabled"


class SuggestionResponse(BaseModel):
    suggestion_id: SuggestionId
    question: str


class AssistantResponse(BaseModel):
    state: AssistantState
    resumes_at: datetime | None
    suggestions: list[SuggestionResponse]


class AnswerRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class StepEventBody(BaseModel):
    kind: Literal[AnswerEventKind.STEP] = AnswerEventKind.STEP
    step: int
    tool: ToolName
    status: StepStatus


class TextEventBody(BaseModel):
    kind: Literal[AnswerEventKind.TEXT] = AnswerEventKind.TEXT
    delta: str


class RowSourceBody(BaseModel):
    kind: Literal[SourceKind.ROW] = SourceKind.ROW
    table: RowTable
    session_key: int
    meeting_name: str
    year: int
    key: dict[str, int | datetime]
    values: dict[str, str | bool | int | float | datetime | None]


class CitationEventBody(BaseModel):
    kind: Literal[AnswerEventKind.CITATION] = AnswerEventKind.CITATION
    number: int
    source: RowSourceBody | None


class DeclinedEventBody(BaseModel):
    kind: Literal[AnswerEventKind.DECLINED] = AnswerEventKind.DECLINED
    reason: DeclineReason
    suggestion_id: SuggestionId


class DoneEventBody(BaseModel):
    kind: Literal[AnswerEventKind.DONE] = AnswerEventKind.DONE
    outcome: AnswerOutcome


class ErrorEventBody(BaseModel):
    kind: Literal[AnswerEventKind.ERROR] = AnswerEventKind.ERROR
    code: ErrorCode
    detail: str
    request_id: str


type AnswerEventBody = Annotated[
    StepEventBody
    | TextEventBody
    | CitationEventBody
    | DeclinedEventBody
    | DoneEventBody
    | ErrorEventBody,
    Field(discriminator="kind"),
]

# An error before the stream starts is JSON; FastAPI would file a response model under the
# route's media type, so the schema is referenced instead.
BEFORE_THE_STREAM: Responses = {
    status_code: {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema}"}}},
    }
    for status_code, description, schema in (
        (status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid Request", "InvalidRequestResponse"),
        (status.HTTP_503_SERVICE_UNAVAILABLE, "Unavailable", ErrorResponse.__name__),
    )
}


@router.get("/assistant")
async def read_assistant(services: Services) -> AssistantResponse:
    """Whether a question can be asked now, and the questions to suggest."""
    state = (
        AssistantState.AVAILABLE
        if isinstance(services.assistant, AssistantAvailable)
        else AssistantState.DISABLED
    )
    suggestions = [
        SuggestionResponse(suggestion_id=suggestion.suggestion_id, question=suggestion.question)
        for suggestion in SUGGESTIONS
    ]
    return AssistantResponse(state=state, resumes_at=None, suggestions=suggestions)


async def _asked(body: AnswerRequest, services: Services) -> tuple[AssistantAvailable, str]:
    # A dependency, so a refused question is an error before the stream starts.
    assistant = services.assistant
    if not isinstance(assistant, AssistantAvailable):
        raise AssistantDisabledError
    if len(body.question) > assistant.question_max_chars:
        raise RequestValidationError([_too_long(assistant.question_max_chars)])
    return assistant, body.question


@router.post("/answers", response_class=EventSourceResponse, responses=BEFORE_THE_STREAM)
async def answer_question(
    asked: Annotated[tuple[AssistantAvailable, str], Depends(_asked)], request: Request
) -> AsyncIterator[AnswerEventBody | ServerSentEvent]:
    """Answers one question about the races of the clean model. Each event's SSE `event` is its
    `kind`; the stream ends after `done` or `error`. Events have no id: a lost connection means
    asking again. The question is trimmed, and sent to the model providers, never stored."""
    # The models in the annotation are what `data` holds; they put the event schemas in the
    # OpenAPI document, which a ServerSentEvent alone would leave out.
    assistant, question = asked
    events: asyncio.Queue[AnswerEvent] = asyncio.Queue(maxsize=ANSWER_EVENT_BUFFER)
    answering = asyncio.create_task(_answer(assistant, question, events))
    try:
        while True:
            event = await events.get()
            body = _body(event)
            if isinstance(body, ErrorEventBody):
                request.scope.setdefault("state", {})[ERROR_CODE_STATE] = body.code
            yield ServerSentEvent(raw_data=body.model_dump_json(), event=body.kind)
            if isinstance(body, DoneEventBody | ErrorEventBody):
                return
    finally:
        answering.cancel()
        await asyncio.wait((answering,))


async def _answer(
    assistant: AssistantAvailable, question: str, events: asyncio.Queue[AnswerEvent]
) -> None:
    """The stream must end with `done` or `error` once it started, so a failure of the answer
    becomes an `internal_error` event, logged under the request's id."""
    try:
        await assistant.answer(question, events.put)
    except Exception:
        logger.exception("answer_failed", extra=log_fields())
        await events.put(ErrorEvent(AnswerError.INTERNAL_ERROR))


def _body(event: AnswerEvent) -> AnswerEventBody:
    match event:
        case StepEvent(step, tool, step_status):
            return StepEventBody(step=step, tool=tool, status=step_status)
        case TextEvent(delta):
            return TextEventBody(delta=delta)
        case CitationEvent(number, source):
            return CitationEventBody(number=number, source=None if source is None else _row(source))
        case DeclinedEvent(reason, suggestion_id):
            return DeclinedEventBody(reason=reason, suggestion_id=SuggestionId(suggestion_id))
        case DoneEvent(outcome):
            return DoneEventBody(outcome=outcome)
        case _:
            return ErrorEventBody(
                code=ErrorCode(event.code),
                detail=ANSWER_ERROR_DETAILS[event.code],
                request_id=request_id(),
            )


def _row(source: RowSource) -> RowSourceBody:
    return RowSourceBody(
        table=source.table,
        session_key=source.session_key,
        meeting_name=source.meeting_name,
        year=source.year,
        key=dict(source.key),
        values=_numbers(source.values),
    )


def _numbers(
    values: Mapping[str, RowValue],
) -> dict[str, str | bool | int | float | datetime | None]:
    """The API's numbers are JSON numbers; a Decimal of the clean model is sent as a float."""
    return {
        name: float(value) if isinstance(value, Decimal) else value
        for name, value in values.items()
    }


def _too_long(max_chars: int) -> dict[str, object]:
    return {
        "type": "string_too_long",
        "loc": ("body", "question"),
        "msg": f"String should have at most {max_chars} characters",
        "input": None,
        "ctx": {"max_length": max_chars},
    }
