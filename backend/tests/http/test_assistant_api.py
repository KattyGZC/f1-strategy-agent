import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import Request
from fastapi.sse import ServerSentEvent
from fastapi.testclient import TestClient

from f1_strategy.adapters.assistant_suggestions import SUGGESTIONS
from f1_strategy.adapters.assistant_tools import DeclineQuestion
from f1_strategy.adapters.http.app import create_app
from f1_strategy.adapters.http.assistant import (
    ANSWER_ERROR_DETAILS,
    TextEventBody,
    answer_question,
)
from f1_strategy.adapters.http.responses import ErrorCode
from f1_strategy.adapters.http.services import (
    ApiServices,
    Assistant,
    AssistantAvailable,
    api_services,
)
from f1_strategy.adapters.observability import FIELDS
from f1_strategy.adapters.settings import ApiSettings
from f1_strategy.application.assistant import (
    AnswerQuestion,
    Found,
    ResultBlock,
    StopReason,
    TextDelta,
    TurnEnd,
)
from f1_strategy.domain.assistant import AnswerError, RowSource, RowTable, ToolName
from tests.assistant_fakes import (
    LIMITS,
    USAGE,
    FakeModel,
    FakeTimer,
    FakeTool,
    ModelScript,
    Stall,
    cite,
    decline_call,
    final_turn,
    strategy_call,
    tool_turn,
)
from tests.http.api import error_body

QUESTION = "How many stops did Norris make at Monza 2024?"
# A closed stream that does not cancel its answer would wait on it for ever.
CANCEL_WITHIN_S = 5
PIT = RowSource(
    table=RowTable.PIT,
    session_key=9590,
    meeting_name="Italian Grand Prix",
    year=2024,
    key={"driver_number": 4, "lap_number": 17},
    values={
        "date": datetime(2024, 9, 1, 13, 31, tzinfo=UTC),
        "lane_duration": Decimal("24.2"),
        "stop_duration": None,
    },
)
PIT_FOUND = Found((ResultBlock(PIT, title="pit", text="lane_duration: 24.2"),), omitted_rows=0)
SUGGESTIONS_BODY = [
    {"suggestion_id": suggestion.suggestion_id, "question": suggestion.question}
    for suggestion in SUGGESTIONS
]


def available(
    script: ModelScript, tools: tuple[FakeTool, ...] = (), max_chars: int = 500
) -> Assistant:
    model = FakeModel(script)
    answer = AnswerQuestion(model, tools, DeclineQuestion(), FakeTimer(), LIMITS)
    return AssistantAvailable(answer, question_max_chars=max_chars)


@contextmanager
def client_with(settings: ApiSettings, assistant: Assistant) -> Iterator[TestClient]:
    @asynccontextmanager
    async def services() -> AsyncIterator[ApiServices]:
        async with api_services(settings) as running:
            yield replace(running, assistant=assistant)

    options = {"loop_factory": asyncio.SelectorEventLoop}
    with TestClient(create_app(services), backend_options=options) as test_client:
        yield test_client


@dataclass(frozen=True)
class Streamed:
    request_id: str
    events: list[tuple[str, object]]


def answer_events(client: TestClient, question: str = QUESTION) -> Streamed:
    """Every event of the answer's stream, as its SSE `event` and its parsed `data`."""
    received: list[tuple[str, object]] = []
    fields: dict[str, str] = {}
    with client.stream("POST", "/api/answers", json={"question": question}) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in [*response.iter_lines(), ""]:
            if line.startswith(":"):
                continue
            if line:
                name, _, value = line.partition(": ")
                fields[name] = value
                continue
            if fields:
                assert "id" not in fields
                received.append((fields["event"], json.loads(fields["data"])))
                fields = {}
    return Streamed(response.headers["x-request-id"], received)


def test_a_disabled_assistant_says_so_with_its_suggestions(client: TestClient) -> None:
    response = client.get("/api/assistant")

    assert response.status_code == 200
    assert response.json() == {
        "state": "disabled",
        "resumes_at": None,
        "suggestions": SUGGESTIONS_BODY,
    }


def test_an_available_assistant_says_so(settings: ApiSettings) -> None:
    with client_with(settings, available([])) as client:
        response = client.get("/api/assistant")

    assert response.json()["state"] == "available"


def test_the_suggestions_are_four_to_six_with_distinct_ids() -> None:
    ids = [suggestion.suggestion_id for suggestion in SUGGESTIONS]

    assert 4 <= len(ids) <= 6
    assert len(set(ids)) == len(ids)


def test_a_question_to_a_disabled_assistant_is_refused_before_any_stream(
    client: TestClient,
) -> None:
    response = client.post("/api/answers", json={"question": QUESTION})

    assert response.status_code == 503
    assert response.json() == error_body(
        response, "assistant_disabled", "the assistant is turned off on this server"
    )


@pytest.mark.parametrize("question", ["", "   "])
def test_an_empty_question_is_rejected(settings: ApiSettings, question: str) -> None:
    with client_with(settings, available([])) as client:
        response = client.post("/api/answers", json={"question": question})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_a_question_past_its_length_is_rejected_without_echoing_it(settings: ApiSettings) -> None:
    question = "Who won? " * 3
    with client_with(settings, available([], max_chars=20)) as client:
        response = client.post("/api/answers", json={"question": f"  {question}  "})

    assert response.status_code == 422
    assert response.json() == {
        **error_body(response, "invalid_request", "the request does not match the API schema"),
        "errors": [
            {
                "loc": ["body", "question"],
                "msg": "String should have at most 20 characters",
                "type": "string_too_long",
            }
        ],
    }
    assert "Who won" not in response.text


def test_a_question_at_its_length_after_trimming_is_answered(settings: ApiSettings) -> None:
    with client_with(settings, available([final_turn(TextDelta("Yes."))], max_chars=8)) as client:
        events = answer_events(client, "  Who won?  ").events

    assert events[-1] == ("done", {"kind": "done", "outcome": "answered"})


def test_an_answer_streams_its_steps_text_and_citations_and_ends_answered(
    settings: ApiSettings,
) -> None:
    strategy = FakeTool(ToolName.DRIVER_STRATEGY, [PIT_FOUND])
    script: ModelScript = [
        [TextDelta("Let me check. "), *tool_turn(strategy_call())],
        final_turn(TextDelta("Norris stopped on lap 17."), cite(PIT), cite(PIT)),
    ]

    with client_with(settings, available(script, (strategy,))) as client:
        events = answer_events(client).events

    source = {
        "kind": "row",
        "table": "pit",
        "session_key": 9590,
        "meeting_name": "Italian Grand Prix",
        "year": 2024,
        "key": {"driver_number": 4, "lap_number": 17},
        "values": {"date": "2024-09-01T13:31:00Z", "lane_duration": 24.2, "stop_duration": None},
    }
    assert events == [
        ("text", {"kind": "text", "delta": "Let me check. "}),
        ("step", {"kind": "step", "step": 1, "tool": "driver_strategy", "status": "running"}),
        ("step", {"kind": "step", "step": 1, "tool": "driver_strategy", "status": "done"}),
        ("text", {"kind": "text", "delta": "Norris stopped on lap 17."}),
        ("citation", {"kind": "citation", "number": 1, "source": source}),
        ("citation", {"kind": "citation", "number": 1, "source": None}),
        ("done", {"kind": "done", "outcome": "answered"}),
    ]
    assert strategy.calls == [{"session_key": 9590, "driver_number": 4}]


def test_a_declined_question_names_its_reason_and_suggestion(settings: ApiSettings) -> None:
    with client_with(settings, available([tool_turn(decline_call())])) as client:
        events = answer_events(client).events

    assert events == [
        (
            "declined",
            {"kind": "declined", "reason": "future_race", "suggestion_id": "norris_monza_stops"},
        ),
        ("done", {"kind": "done", "outcome": "declined"}),
    ]


def test_an_answer_cut_short_ends_with_its_code_detail_and_request_id(
    settings: ApiSettings,
) -> None:
    script: ModelScript = [[TextDelta("Norris"), TurnEnd(StopReason.MAX_TOKENS, USAGE)]]

    with client_with(settings, available(script)) as client:
        streamed = answer_events(client)

    assert streamed.events == [
        ("text", {"kind": "text", "delta": "Norris"}),
        (
            "error",
            {
                "kind": "error",
                "code": "answer_too_long",
                "detail": "the answer grew past its length limit",
                "request_id": streamed.request_id,
            },
        ),
    ]


def test_a_failure_inside_the_answer_ends_the_stream_with_an_internal_error_and_is_logged(
    settings: ApiSettings, caplog: pytest.LogCaptureFixture
) -> None:
    script: ModelScript = [[TurnEnd(StopReason.PAUSE_TURN, USAGE)]]

    with (
        caplog.at_level(logging.INFO, "f1_strategy.http"),
        client_with(settings, available(script)) as client,
    ):
        streamed = answer_events(client)

    assert streamed.events == [
        (
            "error",
            {
                "kind": "error",
                "code": "internal_error",
                "detail": "the API failed on an unexpected error; the logs hold it under this id",
                "request_id": streamed.request_id,
            },
        )
    ]
    failed = [record for record in caplog.records if record.message == "answer_failed"]
    assert len(failed) == 1
    assert failed[0].exc_info is not None
    assert "pause_turn" in str(failed[0].exc_info[1])
    requests = [record for record in caplog.records if record.message == "request"]
    assert requests[-1].__dict__[FIELDS]["code"] == "internal_error"


def test_every_answer_error_is_an_api_error_code_with_a_detail() -> None:
    assert {ErrorCode(code) for code in AnswerError} <= set(ErrorCode)
    assert set(ANSWER_ERROR_DETAILS) == set(AnswerError)


def test_an_enabled_assistant_does_not_start_without_its_language_model(
    settings: ApiSettings,
) -> None:
    enabled = settings.model_copy(update={"assistant_enabled": True})
    options = {"loop_factory": asyncio.SelectorEventLoop}

    with (
        pytest.raises(RuntimeError, match="language model adapter"),
        TestClient(create_app(lambda: api_services(enabled)), backend_options=options),
    ):
        pass


@pytest.mark.anyio
async def test_a_stream_the_browser_closes_cancels_its_answer_and_model_call() -> None:
    model = FakeModel([Stall([TextDelta("Let me check. ")])])
    answer = AnswerQuestion(model, (), DeclineQuestion(), FakeTimer(), LIMITS)
    assistant = AssistantAvailable(answer, question_max_chars=500)
    received: list[object] = []
    first = asyncio.Event()

    async def read() -> None:
        async for body in answer_question((assistant, QUESTION), Request({"type": "http"})):
            received.append(body)
            first.set()

    reading = asyncio.create_task(read())
    await first.wait()
    reading.cancel()
    async with asyncio.timeout(CANCEL_WITHIN_S):
        await asyncio.wait((reading,))

    assert received == [
        ServerSentEvent(
            raw_data=TextEventBody(delta="Let me check. ").model_dump_json(), event="text"
        )
    ]
    assert model.closed_turns == 1
