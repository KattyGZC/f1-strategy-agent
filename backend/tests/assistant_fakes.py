"""A scripted model, fake tools and a timer for the answer use case, and what they say."""

import asyncio
from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass, field

from f1_strategy.application.assistant import (
    AnswerLimits,
    CitationDelta,
    Declined,
    Empty,
    Found,
    ModelEvent,
    Rejected,
    ResultBlock,
    StopReason,
    TokenUsage,
    ToolCall,
    ToolSpec,
    TranscriptEntry,
    TurnEnd,
)
from f1_strategy.domain.assistant import (
    DeclineReason,
    RowSource,
    RowTable,
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
        call_id,
        ToolName.DECLINE_QUESTION,
        {"reason": "future_race", "suggestion_id": "norris_monza_stops"},
    )


def tool_turn(*calls: ToolCall) -> list[ModelEvent]:
    return [*calls, TurnEnd(StopReason.TOOL_USE, USAGE)]


def final_turn(*events: ModelEvent) -> list[ModelEvent]:
    return [*events, TurnEnd(StopReason.END_TURN, USAGE)]


@dataclass(frozen=True)
class Stall:
    """A model turn that sends its events and then nothing more; it expires the timer first."""

    events: Sequence[ModelEvent] = ()


type ModelScript = list[list[ModelEvent] | Stall | Exception]


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

    turns: ModelScript
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


DECLINED = Declined(DeclineReason.FUTURE_RACE, "norris_monza_stops")


def cite(source: RowSource) -> CitationDelta:
    return CitationDelta(source_id(source))
