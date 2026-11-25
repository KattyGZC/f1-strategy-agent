"""The answer use case: a bounded loop of model turns and tool calls behind ports (ADR 0021).

The loop asks the model, runs the tools it calls, sends their results back and repeats until the
model ends its turn, the question is declined, or a limit is reached (ADR 0022). An invalid input
or a failed tool goes back to the model and counts as a round; every other end is an event.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from f1_strategy.domain.assistant import (
    AnswerError,
    AnswerEvent,
    AnswerOutcome,
    CitationLedger,
    DeclinedEvent,
    DeclineReason,
    DoneEvent,
    ErrorEvent,
    Source,
    StepEvent,
    StepStatus,
    TextEvent,
    ToolName,
)

logger = logging.getLogger("f1_strategy.assistant")


class StopReason(StrEnum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    PAUSE_TURN = "pause_turn"
    REFUSAL = "refusal"
    MODEL_CONTEXT_WINDOW_EXCEEDED = "model_context_window_exceeded"


class ModelUnavailableError(Exception):
    """The model is overloaded or failing after its retries."""


class SpendLimitReachedError(Exception):
    """The provider refuses calls until its spend limit resets."""


class ToolFailedError(Exception):
    """A tool could not run, for a reason the model may work around."""


class UnexpectedStopReasonError(RuntimeError):
    def __init__(self, stop_reason: StopReason) -> None:
        super().__init__(f"the model stopped with {stop_reason}, which the answer does not handle")
        self.stop_reason = stop_reason


class ToolNotOfferedError(LookupError):
    def __init__(self, tool: ToolName) -> None:
        super().__init__(f"the model called {tool}, which this answer does not offer")
        self.tool = tool


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class CitationDelta:
    """A citation of the text sent before it, naming a result block's source id."""

    source_id: str


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    tool: ToolName
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class TurnEnd:
    stop_reason: StopReason
    usage: TokenUsage


type ModelEvent = TextDelta | CitationDelta | ToolCall | TurnEnd


@dataclass(frozen=True)
class ResultBlock:
    """One citable block of a tool's result: a row or an article, as the model reads it."""

    source: Source
    title: str
    text: str


@dataclass(frozen=True)
class Found:
    """`omitted_rows` counts the rows past the tool's cap, which the model can narrow to."""

    blocks: tuple[ResultBlock, ...]
    omitted_rows: int


@dataclass(frozen=True)
class Empty:
    message: str


@dataclass(frozen=True)
class Rejected:
    """The tool's input failed its validation; `message` says which field and why."""

    message: str


@dataclass(frozen=True)
class Failed:
    pass


@dataclass(frozen=True)
class Declined:
    reason: DeclineReason
    suggestion_id: str


@dataclass(frozen=True)
class Question:
    text: str


@dataclass(frozen=True)
class ModelTurn:
    text: str
    tool_calls: tuple[ToolCall, ...]


@dataclass(frozen=True)
class ToolReply:
    call_id: str
    result: Found | Empty | Rejected | Failed


@dataclass(frozen=True)
class ToolReplies:
    replies: tuple[ToolReply, ...]


type TranscriptEntry = Question | ModelTurn | ToolReplies


@dataclass(frozen=True)
class ToolSpec:
    name: ToolName
    input_schema: Mapping[str, object]


class LanguageModel(Protocol):
    def turn(
        self, transcript: Sequence[TranscriptEntry], tools: Sequence[ToolSpec]
    ) -> AsyncGenerator[ModelEvent, None]:
        """One model turn, streamed; it ends with a `TurnEnd`. Raises `ModelUnavailableError`
        or `SpendLimitReachedError` when the model cannot answer."""
        ...


class DataTool(Protocol):
    @property
    def spec(self) -> ToolSpec: ...

    async def run(self, arguments: Mapping[str, object]) -> Found | Empty | Rejected:
        """Raises `ToolFailedError` when it cannot run."""
        ...


class DeclineTool(Protocol):
    @property
    def spec(self) -> ToolSpec: ...

    async def run(self, arguments: Mapping[str, object]) -> Declined | Rejected: ...


class Timer(Protocol):
    async def sleep(self, seconds: float) -> None: ...


@dataclass(frozen=True)
class AnswerLimits:
    max_tool_rounds: int
    answer_timeout_s: float


type EventSink = Callable[[AnswerEvent], Awaitable[None]]


@dataclass(frozen=True)
class _Wiring:
    model: LanguageModel
    tools: Mapping[ToolName, DataTool]
    decline: DeclineTool
    specs: tuple[ToolSpec, ...]
    max_tool_rounds: int


@dataclass(frozen=True)
class _TurnOutcome:
    turn: ModelTurn
    stop_reason: StopReason


class AnswerQuestion:
    def __init__(
        self,
        model: LanguageModel,
        tools: Sequence[DataTool],
        decline: DeclineTool,
        timer: Timer,
        limits: AnswerLimits,
    ) -> None:
        self._wiring = _Wiring(
            model,
            {tool.spec.name: tool for tool in tools},
            decline,
            (*(tool.spec for tool in tools), decline.spec),
            limits.max_tool_rounds,
        )
        self._timer = timer
        self._answer_timeout_s = limits.answer_timeout_s

    async def __call__(self, question: str, emit: EventSink) -> None:
        """Emits the answer's events; the last one is a `DoneEvent` or an `ErrorEvent`."""
        answer = asyncio.create_task(_Answer(self._wiring, emit).run(question))
        deadline = asyncio.create_task(self._timer.sleep(self._answer_timeout_s))
        try:
            await asyncio.wait((answer, deadline), return_when=asyncio.FIRST_COMPLETED)
        finally:
            answer.cancel()
            deadline.cancel()
            await asyncio.wait((answer, deadline))
        if answer.cancelled():
            await emit(ErrorEvent(AnswerError.ANSWER_TIMEOUT))
            return
        answer.result()


class _Answer:
    """The state of one answer: its transcript, its ledger and its steps."""

    def __init__(self, wiring: _Wiring, emit: EventSink) -> None:
        self._wiring = wiring
        self._emit = emit
        self._ledger = CitationLedger()
        self._steps = 0

    async def run(self, question: str) -> None:
        transcript: list[TranscriptEntry] = [Question(question)]
        rounds = 0
        while True:
            try:
                outcome = await self._model_turn(transcript)
            except ModelUnavailableError:
                return await self._emit(ErrorEvent(AnswerError.MODEL_UNAVAILABLE))
            except SpendLimitReachedError:
                return await self._emit(ErrorEvent(AnswerError.ASSISTANT_PAUSED))
            end = _end_of_turn(outcome.stop_reason)
            if end is not None:
                return await self._emit(end)
            if rounds == self._wiring.max_tool_rounds:
                return await self._emit(ErrorEvent(AnswerError.TOOL_ROUNDS_EXCEEDED))
            rounds += 1
            replies = await self._run_tools(outcome.turn.tool_calls)
            if replies is None:
                return None
            transcript += [outcome.turn, replies]

    async def _model_turn(self, transcript: Sequence[TranscriptEntry]) -> _TurnOutcome:
        wiring = self._wiring
        text: list[str] = []
        calls: list[ToolCall] = []
        async with aclosing(wiring.model.turn(transcript, wiring.specs)) as events:
            async for event in events:
                match event:
                    case TextDelta(delta):
                        text.append(delta)
                        await self._emit(TextEvent(delta))
                    case CitationDelta(cited_id):
                        await self._cite(cited_id)
                    case ToolCall():
                        calls.append(event)
                    case _:
                        turn = ModelTurn("".join(text), tuple(calls))
                        return _TurnOutcome(turn, event.stop_reason)
        raise RuntimeError("the model's turn ended without a TurnEnd")

    async def _cite(self, cited_id: str) -> None:
        citation = self._ledger.cite(cited_id)
        if citation is None:
            logger.warning("citation_dropped", extra={"source_id": cited_id})
            return
        await self._emit(citation)

    async def _run_tools(self, calls: Sequence[ToolCall]) -> ToolReplies | None:
        """None when a call declined the question, which ends the answer."""
        replies: list[ToolReply] = []
        for call in calls:
            if call.tool is ToolName.DECLINE_QUESTION:
                result = await self._wiring.decline.run(call.arguments)
                if isinstance(result, Declined):
                    await self._emit(DeclinedEvent(result.reason, result.suggestion_id))
                    await self._emit(DoneEvent(AnswerOutcome.DECLINED))
                    return None
                replies.append(ToolReply(call.call_id, result))
            else:
                replies.append(ToolReply(call.call_id, await self._run_data_tool(call)))
        return ToolReplies(tuple(replies))

    async def _run_data_tool(self, call: ToolCall) -> Found | Empty | Rejected | Failed:
        tool = self._wiring.tools.get(call.tool)
        if tool is None:
            raise ToolNotOfferedError(call.tool)
        self._steps += 1
        step = self._steps
        await self._emit(StepEvent(step, call.tool, StepStatus.RUNNING))
        try:
            result = await tool.run(call.arguments)
        except ToolFailedError:
            await self._emit(StepEvent(step, call.tool, StepStatus.FAILED))
            return Failed()
        if isinstance(result, Found):
            for block in result.blocks:
                self._ledger.record(block.source)
        await self._emit(StepEvent(step, call.tool, _STEP_STATUS[type(result)]))
        return result


_STEP_STATUS = {Found: StepStatus.DONE, Empty: StepStatus.EMPTY, Rejected: StepStatus.REJECTED}


def _end_of_turn(stop_reason: StopReason) -> AnswerEvent | None:
    """The answer's last event when the turn ends it, or None when the model called tools."""
    match stop_reason:
        case StopReason.TOOL_USE:
            return None
        case StopReason.END_TURN:
            return DoneEvent(AnswerOutcome.ANSWERED)
        case StopReason.MAX_TOKENS:
            return ErrorEvent(AnswerError.ANSWER_TOO_LONG)
        case StopReason.REFUSAL:
            return ErrorEvent(AnswerError.MODEL_REFUSED)
        case _:
            raise UnexpectedStopReasonError(stop_reason)
