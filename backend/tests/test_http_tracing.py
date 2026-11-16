"""The request middleware and the error shape, on apps that need no store (ADR 0016)."""

import io
import json
import logging
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from f1_strategy.adapters.http.app import create_app
from f1_strategy.adapters.http.errors import handler_for, install_error_handlers
from f1_strategy.adapters.http.tracing import RequestTracing
from f1_strategy.adapters.observability import JsonFormatter
from f1_strategy.application.replay import ReplayNotFoundError

EDGE_ID = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def log() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("f1_strategy.http")
    level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield stream
    logger.removeHandler(handler)
    logger.setLevel(level)


def logged(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def request_line(stream: io.StringIO) -> dict[str, object]:
    (line,) = [line for line in logged(stream) if line["event"] == "request"]
    line.pop("ts")
    return line


def test_a_response_carries_a_new_request_id_and_its_request_is_logged_once(
    log: io.StringIO,
) -> None:
    response = TestClient(create_app()).get("/api/health")

    request_id = response.headers["x-request-id"]
    line = request_line(log)
    assert response.status_code == 200
    assert len(request_id) == 32
    assert isinstance(line.pop("duration_ms"), float)
    assert line == {
        "level": "INFO",
        "logger": "f1_strategy.http",
        "event": "request",
        "request_id": request_id,
        "method": "GET",
        "route": "/api/health",
        "status": 200,
        "code": None,
    }


def test_the_edge_request_id_is_kept_on_the_response_and_the_log(log: io.StringIO) -> None:
    response = TestClient(create_app()).get("/api/health", headers={"X-Request-ID": EDGE_ID})

    assert response.headers["x-request-id"] == EDGE_ID
    assert request_line(log)["request_id"] == EDGE_ID


def test_a_client_id_that_could_write_into_the_logs_is_replaced() -> None:
    response = TestClient(create_app()).get("/api/health", headers={"X-Request-ID": "a b"})

    assert response.headers["x-request-id"] != "a b"
    assert len(response.headers["x-request-id"]) == 32


UNROUTED = {
    "unknown path": (("GET", "/api/missing"), 404, "route_not_found", "no API route has this path"),
    "wrong method": (
        ("POST", "/api/health"),
        405,
        "method_not_allowed",
        "this route does not accept the method",
    ),
}


@pytest.mark.parametrize(("request_", "status", "code", "detail"), UNROUTED.values(), ids=UNROUTED)
def test_a_request_the_router_cannot_route_answers_in_the_error_shape(
    log: io.StringIO, request_: tuple[str, str], status: int, code: str, detail: str
) -> None:
    response = TestClient(create_app()).request(*request_)

    assert response.status_code == status
    assert response.json() == {
        "detail": detail,
        "code": code,
        "request_id": response.headers["x-request-id"],
    }
    assert (request_line(log)["status"], request_line(log)["code"]) == (status, code)


def test_an_unexpected_error_is_logged_with_its_route_and_answered_without_its_traceback(
    log: io.StringIO,
) -> None:
    response = TestClient(create_app()).get("/api/replays/abc")

    (unhandled,) = [line for line in logged(log) if line["event"] == "unhandled_error"]
    assert response.status_code == 500
    assert "Traceback" not in response.text
    assert unhandled["route"] == "/api/replays/{replay_id}"
    assert unhandled["request_id"] == response.headers["x-request-id"]
    assert str(unhandled["traceback"]).endswith(
        "RuntimeError: the API services are not running; start the app with its lifespan"
    )
    assert (request_line(log)["status"], request_line(log)["code"]) == (500, "internal_error")


def tiny_app(*, traced: bool = True) -> FastAPI:
    app = FastAPI()

    @app.get("/teapot")
    async def teapot() -> None:
        raise HTTPException(status_code=418)

    @app.get("/replay")
    async def replay() -> None:
        raise ReplayNotFoundError("gone")

    install_error_handlers(app)
    if traced:
        app.add_middleware(RequestTracing)
    return app


def test_an_http_error_the_router_does_not_raise_on_its_own_is_an_internal_error() -> None:
    response = TestClient(tiny_app()).get("/teapot")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"


def test_an_error_answered_outside_the_request_middleware_fails_loud() -> None:
    with pytest.raises(RuntimeError, match=r"^no request id: the request middleware is not"):
        TestClient(tiny_app(traced=False)).get("/replay")


def test_a_handler_called_with_another_error_raises_it_again() -> None:
    def handle(_: Request, __: KeyError) -> JSONResponse:
        return JSONResponse({})

    with pytest.raises(ValueError, match=r"^other$"):
        handler_for(KeyError, handle)(Request({"type": "http"}), ValueError("other"))


async def streams_then_fails(_: Scope, __: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"partial", "more_body": True})
    raise RuntimeError("stream broke")


def test_an_error_after_the_response_started_is_logged_and_raised_again(log: io.StringIO) -> None:
    client = TestClient(RequestTracing(streams_then_fails))

    with pytest.raises(RuntimeError, match=r"^stream broke$"):
        client.get("/events")

    assert [line["event"] for line in logged(log)] == ["unhandled_error", "request"]
    assert request_line(log)["status"] == 200


@pytest.mark.anyio
async def test_a_lifespan_passes_through_untraced() -> None:
    seen: list[str] = []

    async def lifespan_app(scope: Scope, _: Receive, __: Send) -> None:
        seen.append(scope["type"])

    await RequestTracing(lifespan_app)({"type": "lifespan"}, _never, _ignore)

    assert seen == ["lifespan"]


async def _never() -> dict[str, object]:
    raise AssertionError


async def _ignore(_: object) -> None:
    raise AssertionError


async def routed_elsewhere(scope: Scope, _: Receive, send: Send) -> None:
    scope["route"] = SimpleNamespace(path="/other/{name}")
    scope["path_params"] = {"name": "x"}
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def test_a_route_whose_path_the_request_does_not_end_with_is_logged_as_it_is(
    log: io.StringIO,
) -> None:
    TestClient(RequestTracing(routed_elsewhere)).get("/api/thing")

    assert request_line(log)["route"] == "/other/{name}"


def test_a_route_of_an_included_router_is_logged_with_its_prefix(log: io.StringIO) -> None:
    TestClient(create_app()).get("/api/replays/abc/events")

    assert request_line(log)["route"] == "/api/replays/{replay_id}/events"
