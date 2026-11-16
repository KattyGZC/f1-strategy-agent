import json
import logging

import pytest

from f1_strategy.adapters.observability import (
    JsonFormatter,
    configure_logging,
    current_request_id,
    log_fields,
    request_id_from,
)


def test_a_request_id_from_the_edge_is_kept() -> None:
    assert request_id_from("4f0c9b1e-aa") == "4f0c9b1e-aa"


@pytest.mark.parametrize(
    "header",
    [None, "", "has space", "line\nbreak", "x" * 65, '{"json": 1}'],
    ids=["absent", "empty", "space", "newline", "too long", "json"],
)
def test_anything_else_is_replaced_by_a_new_id(header: str | None) -> None:
    generated = request_id_from(header)

    assert generated != header
    assert len(generated) == 32
    assert set(generated) <= set("0123456789abcdef")


def test_two_new_ids_differ() -> None:
    assert request_id_from(None) != request_id_from(None)


def record(message: str, **extra: object) -> logging.LogRecord:
    made = logging.makeLogRecord({"name": "f1_strategy.http", "levelname": "INFO", "msg": message})
    made.created = 1763200000.25
    for key, value in extra.items():
        setattr(made, key, value)
    return made


def test_a_line_is_one_json_object_with_the_request_id_and_its_fields() -> None:
    token = current_request_id.set("abc")
    try:
        line = JsonFormatter().format(record("request", **log_fields(status=200, route=None)))
    finally:
        current_request_id.reset(token)

    assert json.loads(line) == {
        "ts": "2025-11-15T09:46:40.250000+00:00",
        "level": "INFO",
        "logger": "f1_strategy.http",
        "event": "request",
        "request_id": "abc",
        "status": 200,
        "route": None,
    }


def test_a_line_outside_a_request_has_no_request_id() -> None:
    assert json.loads(JsonFormatter().format(record("started")))["request_id"] is None


def fail() -> None:
    raise ValueError("boom")


def test_an_exception_is_written_with_its_traceback() -> None:
    try:
        fail()
    except ValueError as error:
        failed = record("unhandled_error", exc_info=(ValueError, error, error.__traceback__))

    traceback = json.loads(JsonFormatter().format(failed))["traceback"]

    assert traceback.startswith("Traceback (most recent call last):")
    assert traceback.endswith("ValueError: boom")


@pytest.mark.usefixtures("restored_logging")
def test_logging_writes_every_logger_through_one_json_handler(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging.getLogger("uvicorn.error").addHandler(logging.NullHandler())

    configure_logging("WARNING")
    logging.getLogger("uvicorn.error").warning("from uvicorn")
    logging.getLogger("f1_strategy.below").info("below the level")

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(line["logger"], line["event"]) for line in lines] == [
        ("uvicorn.error", "from uvicorn")
    ]
    assert logging.getLogger("uvicorn.access").disabled
    assert logging.getLogger("uvicorn.error").handlers == []
