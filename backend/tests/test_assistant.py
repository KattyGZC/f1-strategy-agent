import asyncio
import logging
from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass, field

import pytest

from f1_strategy.application.assistant import (
    AnswerLimits,
    AnswerQuestion,
    CitationDelta,
    Declined,
    Empty,
    Failed,
    Found,
    ModelEvent,
    ModelTurn,
    ModelUnavailableError,
    Question,
    Rejected,
    ResultBlock,
    SpendLimitReachedError,
    StopReason,
    TextDelta,
    TokenUsage,
    ToolCall,
    ToolFailedError,
    ToolNotOfferedError,
    ToolReplies,
    ToolReply,
    ToolSpec,
    TranscriptEntry,
    TurnEnd,
    UnexpectedStopReasonError,
)
from f1_strategy.domain.assistant import (
    AnswerError,
    AnswerEvent,
    AnswerOutcome,
    CitationEvent,
    DeclinedEvent,
    DeclineReason,
    DoneEvent,
    ErrorEvent,
    RowSource,
    RowTable,
    StepEvent,
    StepStatus,
    TextEvent,
    ToolName,
    source_id,
)

QUESTION = "How many stops did Norris make at Monza 2024?"
LIMITS = AnswerLimits(max_tool_rounds=6, answer_timeout_s=60)
USAGE = TokenUsage(input_tokens=1200, cache_write_tokens=0, cache_read_tokens=0, output_tokens=80)
STINT = RowSource(
    table=RowTable.STINT,
    session_key=9590,
    meeting_name="Italian Grand Prix",
    year=2024,
    key={"driver_number": 4, "stint_number": 2},
    values={"compound": "HARD", "lap_start": 17, "lap_end": 53},
)
STINTS_FOUND = Found(
    (ResultBlock(STINT, title="Norris, stint 2", text="HARD, laps 17 to 53"),), omitted_rows=0
)
NORRIS = {"session_key": 9590, "driver_number": 4}


def strategy_call(call_id: str = "call_1") -> ToolCall:
    return ToolCall(call_id, ToolName.DRIVER_STRATEGY, NORRIS)


def decline_call(call_id: str = "call_1") -> ToolCall:
    return ToolCall(
        call_id, ToolName.DECLINE_QUESTION, {"reason": "future_race", "suggestion_id": "monza"}
    )


def tool_turn(*calls: ToolCall) -> list[ModelEvent]:
    return [*calls, TurnEnd(StopReason.TOOL_USE, USAGE)]


def final_turn(*events: ModelEvent) -> list[ModelEvent]:
    return [*events, TurnEnd(StopReason.END_TURN, USAGE)]


@dataclass(frozen=True)
class Stall:
    """A model turn that sends its events and then nothing more; it expires the timer first."""

    events: Sequence[ModelEvent] = ()


@dataclass
class FakeTimer:
    expired: asyncio.Event = field(default_factory=asyncio.Event)
    slept_s: list[float] = field(default_factory=list)

    async def sleep(self, seconds: float) -> None:
        self.slept_s.append(seconds)
        await self.expired.wait()


@dataclass
class FakeModel:
    """Plays one scripted turn per call and keeps the transcript and tools of each."""

    turns: list[list[ModelEvent] | Stall | Exception]
    timer: FakeTimer = field(default_factory=FakeTimer)
    transcripts: list[list[TranscriptEntry]] = field(default_factory=list)
    offered: list[list[ToolSpec]] = field(default_factory=list)
    closed_turns: int = 0

    async def turn(
        self, transcript: Sequence[TranscriptEntry], tools: Sequence[ToolSpec]
    ) -> AsyncGenerator[ModelEvent, None]:
        self.transcripts.append(list(transcript))
        self.offered.append(list(tools))
        script = self.turns[len(self.transcripts) - 1]
        try:
            if isinstance(script, Exception):
                raise script
            events = script.events if isinstance(script, Stall) else script
            for event in events:
                yield event
            if isinstance(script, Stall):
                self.timer.expired.set()
                await asyncio.Event().wait()
        finally:
            self.closed_turns += 1


@dataclass
class FakeTool:
    name: ToolName
    results: list[Found | Empty | Rejected | Exception]
    calls: list[Mapping[str, object]] = field(default_factory=list)

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, {"type": "object", "title": self.name})

    async def run(self, arguments: Mapping[str, object]) -> Found | Empty | Rejected:
        self.calls.append(arguments)
        result = self.results[len(self.calls) - 1]
        if isinstance(result, Exception):
            raise result
        return result


@dataclass
class FakeDecline:
    results: list[Declined | Rejected]
    calls: list[Mapping[str, object]] = field(default_factory=list)

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(ToolName.DECLINE_QUESTION, {"type": "object"})

    async def run(self, arguments: Mapping[str, object]) -> Declined | Rejected:
        self.calls.append(arguments)
        return self.results[len(self.calls) - 1]


DECLINED = Declined(DeclineReason.FUTURE_RACE, "monza")


async def answer(
    model: FakeModel,
    tools: Sequence[FakeTool] = (),
    decline: FakeDecline | None = None,
    limits: AnswerLimits = LIMITS,
) -> list[AnswerEvent]:
    events: list[AnswerEvent] = []

    async def emit(event: AnswerEvent) -> None:
        events.append(event)

    use_case = AnswerQuestion(model, tools, decline or FakeDecline([DECLINED]), model.timer, limits)
    await use_case(QUESTION, emit)
    return events


@pytest.mark.anyio
async def test_an_answer_streams_its_steps_text_and_citations_and_ends_answered() -> None:
    strategy = FakeTool(ToolName.DRIVER_STRATEGY, [STINTS_FOUND])
    model = FakeModel(
        [
            [TextDelta("Let me check. "), *tool_turn(strategy_call())],
            final_turn(TextDelta("Norris stopped once, "), TextDelta("onto hards."), cite(STINT)),
        ]
    )

    events = await answer(model, [strategy])

    assert events == [
        TextEvent("Let me check. "),
        StepEvent(1, ToolName.DRIVER_STRATEGY, StepStatus.RUNNING),
        StepEvent(1, ToolName.DRIVER_STRATEGY, StepStatus.DONE),
        TextEvent("Norris stopped once, "),
        TextEvent("onto hards."),
        CitationEvent(1, STINT),
        DoneEvent(AnswerOutcome.ANSWERED),
    ]
    assert strategy.calls == [NORRIS]
    assert model.transcripts[1] == [
        Question(QUESTION),
        ModelTurn("Let me check. ", (strategy_call(),)),
        ToolReplies((ToolReply("call_1", STINTS_FOUND),)),
    ]


def cite(source: RowSource) -> CitationDelta:
    return CitationDelta(source_id(source))


@pytest.mark.anyio
async def test_every_turn_is_offered_the_data_tools_and_the_decline() -> None:
    strategy = FakeTool(ToolName.DRIVER_STRATEGY, [])
    weather = FakeTool(ToolName.WEATHER, [])
    model = FakeModel([final_turn(TextDelta("Hello."))])

    await answer(model, [strategy, weather])

    assert model.offered == [[strategy.spec, weather.spec, FakeDecline([]).spec]]


@pytest.mark.anyio
async def test_the_calls_of_one_turn_run_in_order_as_one_round_with_numbered_steps() -> None:
    strategy = FakeTool(ToolName.DRIVER_STRATEGY, [STINTS_FOUND, Empty("no stints for 81")])
    model = FakeModel(
        [
            tool_turn(strategy_call("call_1"), ToolCall("call_2", ToolName.DRIVER_STRATEGY, {})),
            final_turn(),
        ]
    )

    events = await answer(model, [strategy], limits=AnswerLimits(1, 60))

    assert events == [
        StepEvent(1, ToolName.DRIVER_STRATEGY, StepStatus.RUNNING),
        StepEvent(1, ToolName.DRIVER_STRATEGY, StepStatus.DONE),
        StepEvent(2, ToolName.DRIVER_STRATEGY, StepStatus.RUNNING),
        StepEvent(2, ToolName.DRIVER_STRATEGY, StepStatus.EMPTY),
        DoneEvent(AnswerOutcome.ANSWERED),
    ]
    assert model.transcripts[1][-1] == ToolReplies(
        (
            ToolReply("call_1", STINTS_FOUND),
            ToolReply("call_2", Empty("no stints for 81")),
        )
    )


@pytest.mark.anyio
async def test_a_turn_asking_for_tools_past_the_last_round_ends_the_answer_unrun() -> None:
    strategy = FakeTool(ToolName.DRIVER_STRATEGY, [STINTS_FOUND, STINTS_FOUND])
    model = FakeModel([tool_turn(strategy_call()), tool_turn(strategy_call())])

    events = await answer(model, [strategy], limits=AnswerLimits(1, 60))

    assert events[-1] == ErrorEvent(AnswerError.TOOL_ROUNDS_EXCEEDED)
    assert strategy.calls == [NORRIS]
    assert len(model.transcripts) == 2


@pytest.mark.anyio
async def test_an_invalid_input_goes_back_to_the_model_rejected_and_counts_as_a_round() -> None:
    rejected = Rejected("driver_number: must be greater than 0")
    strategy = FakeTool(ToolName.DRIVER_STRATEGY, [rejected])
    model = FakeModel([tool_turn(strategy_call()), tool_turn(strategy_call())])

    events = await answer(model, [strategy], limits=AnswerLimits(1, 60))

    assert events == [
        StepEvent(1, ToolName.DRIVER_STRATEGY, StepStatus.RUNNING),
        StepEvent(1, ToolName.DRIVER_STRATEGY, StepStatus.REJECTED),
        ErrorEvent(AnswerError.TOOL_ROUNDS_EXCEEDED),
    ]
    assert model.transcripts[1][-1] == ToolReplies((ToolReply("call_1", rejected),))


@pytest.mark.anyio
async def test_a_failing_tool_goes_back_to_the_model_as_failed() -> None:
    strategy = FakeTool(ToolName.DRIVER_STRATEGY, [ToolFailedError("the clean store is down")])
    model = FakeModel([tool_turn(strategy_call()), final_turn(TextDelta("I could not check."))])

    events = await answer(model, [strategy])

    assert events == [
        StepEvent(1, ToolName.DRIVER_STRATEGY, StepStatus.RUNNING),
        StepEvent(1, ToolName.DRIVER_STRATEGY, StepStatus.FAILED),
        TextEvent("I could not check."),
        DoneEvent(AnswerOutcome.ANSWERED),
    ]
    assert model.transcripts[1][-1] == ToolReplies((ToolReply("call_1", Failed()),))


@pytest.mark.anyio
async def test_a_tool_raising_anything_else_fails_the_answer_loudly() -> None:
    strategy = FakeTool(ToolName.DRIVER_STRATEGY, [KeyError("compound")])
    model = FakeModel([tool_turn(strategy_call())])

    with pytest.raises(KeyError, match="compound"):
        await answer(model, [strategy])


@pytest.mark.anyio
async def test_an_empty_result_goes_back_to_the_model_with_its_message() -> None:
    empty = Empty("no stints for driver 4 in session 9590")
    strategy = FakeTool(ToolName.DRIVER_STRATEGY, [empty])
    model = FakeModel([tool_turn(strategy_call()), final_turn()])

    events = await answer(model, [strategy])

    assert events[1] == StepEvent(1, ToolName.DRIVER_STRATEGY, StepStatus.EMPTY)
    assert model.transcripts[1][-1] == ToolReplies((ToolReply("call_1", empty),))


@pytest.mark.anyio
async def test_declining_ends_the_answer_declined_without_a_step_or_the_calls_after_it() -> None:
    strategy = FakeTool(ToolName.DRIVER_STRATEGY, [STINTS_FOUND])
    decline = FakeDecline([DECLINED])
    model = FakeModel([tool_turn(decline_call("call_1"), strategy_call("call_2"))])

    events = await answer(model, [strategy], decline)

    assert events == [
        DeclinedEvent(DeclineReason.FUTURE_RACE, "monza"),
        DoneEvent(AnswerOutcome.DECLINED),
    ]
    assert decline.calls == [decline_call().arguments]
    assert strategy.calls == []


@pytest.mark.anyio
async def test_a_decline_with_an_invalid_input_goes_back_to_the_model_rejected() -> None:
    rejected = Rejected("suggestion_id: not one of ours")
    model = FakeModel([tool_turn(decline_call()), final_turn(TextDelta("Sorry."))])

    events = await answer(model, decline=FakeDecline([rejected]))

    assert events == [TextEvent("Sorry."), DoneEvent(AnswerOutcome.ANSWERED)]
    assert model.transcripts[1][-1] == ToolReplies((ToolReply("call_1", rejected),))


@pytest.mark.anyio
async def test_a_citation_of_a_source_no_tool_returned_is_dropped_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy = FakeTool(ToolName.DRIVER_STRATEGY, [STINTS_FOUND])
    model = FakeModel(
        [
            tool_turn(strategy_call()),
            final_turn(TextDelta("Norris stopped twice."), CitationDelta("row:pit:9590:4:30")),
        ]
    )

    with caplog.at_level(logging.WARNING, "f1_strategy.assistant"):
        events = await answer(model, [strategy])

    assert events[-2:] == [TextEvent("Norris stopped twice."), DoneEvent(AnswerOutcome.ANSWERED)]
    assert [(record.message, record.__dict__["source_id"]) for record in caplog.records] == [
        ("citation_dropped", "row:pit:9590:4:30")
    ]


@pytest.mark.anyio
async def test_a_source_cited_again_carries_only_its_number() -> None:
    strategy = FakeTool(ToolName.DRIVER_STRATEGY, [STINTS_FOUND])
    model = FakeModel([tool_turn(strategy_call()), final_turn(cite(STINT), cite(STINT))])

    events = await answer(model, [strategy])

    assert events[2:4] == [CitationEvent(1, STINT), CitationEvent(1, None)]


@pytest.mark.parametrize(
    ("stop_reason", "code"),
    [
        pytest.param(StopReason.MAX_TOKENS, AnswerError.ANSWER_TOO_LONG, id="max-tokens"),
        pytest.param(StopReason.REFUSAL, AnswerError.MODEL_REFUSED, id="refusal"),
    ],
)
@pytest.mark.anyio
async def test_a_turn_cut_short_by_the_model_ends_the_answer_with_its_code(
    stop_reason: StopReason, code: AnswerError
) -> None:
    model = FakeModel([[TextDelta("Norris stopped"), TurnEnd(stop_reason, USAGE)]])

    assert await answer(model) == [TextEvent("Norris stopped"), ErrorEvent(code)]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        pytest.param(ModelUnavailableError("overloaded"), AnswerError.MODEL_UNAVAILABLE, id="down"),
        pytest.param(SpendLimitReachedError("limit"), AnswerError.ASSISTANT_PAUSED, id="spent"),
    ],
)
@pytest.mark.anyio
async def test_a_model_that_cannot_answer_ends_the_answer_with_its_code(
    error: Exception, code: AnswerError
) -> None:
    strategy = FakeTool(ToolName.DRIVER_STRATEGY, [STINTS_FOUND])
    model = FakeModel([tool_turn(strategy_call()), error])

    events = await answer(model, [strategy])

    assert events[-1] == ErrorEvent(code)
    assert model.closed_turns == 2


@pytest.mark.parametrize("stop_reason", [StopReason.PAUSE_TURN, StopReason.STOP_SEQUENCE])
@pytest.mark.anyio
async def test_a_stop_reason_the_loop_does_not_handle_fails_the_answer_naming_it(
    stop_reason: StopReason,
) -> None:
    model = FakeModel([[TurnEnd(stop_reason, USAGE)]])

    with pytest.raises(UnexpectedStopReasonError, match=stop_reason.value):
        await answer(model)


@pytest.mark.anyio
async def test_a_call_of_a_tool_that_was_not_offered_fails_the_answer_naming_it() -> None:
    model = FakeModel([tool_turn(ToolCall("call_1", ToolName.SEARCH_RULES, {"query": "pit"}))])

    with pytest.raises(ToolNotOfferedError, match="search_rules"):
        await answer(model)


@pytest.mark.anyio
async def test_an_answer_past_its_time_ends_with_a_timeout_and_its_model_call_closed() -> None:
    model = FakeModel([Stall([TextDelta("Let me check. ")])])

    events = await answer(model, limits=AnswerLimits(6, answer_timeout_s=60))

    assert events == [TextEvent("Let me check. "), ErrorEvent(AnswerError.ANSWER_TIMEOUT)]
    assert model.timer.slept_s == [60]
    assert model.closed_turns == 1


@pytest.mark.anyio
async def test_an_answer_cancelled_by_its_caller_closes_its_model_call() -> None:
    model = FakeModel([Stall()])
    events: list[AnswerEvent] = []

    async def emit(event: AnswerEvent) -> None:
        events.append(event)

    use_case = AnswerQuestion(model, (), FakeDecline([]), FakeTimer(), LIMITS)
    task = asyncio.create_task(use_case(QUESTION, emit))
    await model.timer.expired.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == []
    assert model.closed_turns == 1


@pytest.mark.anyio
async def test_a_model_turn_that_ends_without_its_end_fails_the_answer() -> None:
    model = FakeModel([[TextDelta("Norris")]])

    with pytest.raises(RuntimeError, match="without a TurnEnd"):
        await answer(model)
