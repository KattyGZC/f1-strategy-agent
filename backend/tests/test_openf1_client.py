from datetime import UTC, datetime

import httpx2
import pytest

from f1_strategy.adapters.openf1 import OpenF1Client, OpenF1Error, RetryPolicy
from f1_strategy.adapters.rate_limit import RateLimit, SlidingWindowRateLimiter
from f1_strategy.domain.openf1 import Endpoint, JsonObject, Param, RawRequest, RawResponse
from tests.factories import FakeClock

BASE_URL = "https://openf1.test/v1"
FETCHED_AT = datetime(2026, 10, 26, 12, tzinfo=UTC)
LAPS = RawRequest.of(Endpoint.LAPS, {Param.SESSION_KEY: 9472})
WINDOW = RawRequest.of(
    Endpoint.CAR_DATA,
    {
        Param.SESSION_KEY: 9472,
        Param.DRIVER_NUMBER: 1,
        Param.DATE_FROM: "2024-03-02T15:00:00+00:00",
        Param.DATE_BEFORE: "2024-03-02T15:30:00+00:00",
    },
)
ROWS: list[JsonObject] = [{"session_key": 9472, "lap_number": 1, "lap_duration": 100.537}]

type Reply = httpx2.Response | httpx2.TransportError


class Server:
    def __init__(self, replies: list[Reply]) -> None:
        self._replies = replies
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        reply = self._replies[min(len(self.requests), len(self._replies)) - 1]
        if isinstance(reply, httpx2.TransportError):
            raise reply
        return reply


class Sleeps:
    def __init__(self) -> None:
        self.seconds: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)


async def fetch(
    request: RawRequest, server: Server, sleeps: Sleeps, max_attempts: int = 3
) -> RawResponse:
    limiter = SlidingWindowRateLimiter([RateLimit(1000, 1.0)])
    async with httpx2.AsyncClient(
        base_url=BASE_URL, transport=httpx2.MockTransport(server)
    ) as http:
        client = OpenF1Client(
            http,
            limiter,
            RetryPolicy(max_attempts, backoff_base_s=1.0),
            sleep=sleeps,
            clock=lambda: FETCHED_AT,
        )
        return await client.fetch(request)


def json_reply(status: int, body: object) -> httpx2.Response:
    return httpx2.Response(status, json=body)


@pytest.mark.anyio
async def test_a_list_body_becomes_the_response_rows() -> None:
    server = Server([json_reply(200, ROWS)])

    response = await fetch(LAPS, server, Sleeps())

    assert response == RawResponse(LAPS, ROWS, FETCHED_AT)
    assert str(server.requests[0].url) == f"{BASE_URL}/laps?session_key=9472"


@pytest.mark.anyio
async def test_date_filters_are_sent_as_operators_not_as_key_value_pairs() -> None:
    server = Server([json_reply(200, [])])

    await fetch(WINDOW, server, Sleeps())

    assert server.requests[0].url.query == (
        b"date%3C2024-03-02T15%3A30%3A00%2B00%3A00"
        b"&date%3E=2024-03-02T15%3A00%3A00%2B00%3A00&driver_number=1&session_key=9472"
    )


@pytest.mark.anyio
async def test_no_results_is_an_empty_response_not_an_error() -> None:
    server = Server([json_reply(404, {"detail": "No results found."})])

    response = await fetch(LAPS, server, Sleeps())

    assert response.rows == []
    assert len(server.requests) == 1


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (json_reply(404, {"detail": "Not Found"}), '404 {"detail":"Not Found"}'),
        (httpx2.Response(404, text="<html>"), "404 <html>"),
        (json_reply(404, ["No results found."]), '404 ["No results found."]'),
        (
            json_reply(422, {"detail": "You're likely asking for too much data at once."}),
            "422 ",
        ),
        (httpx2.Response(200, text="not json"), "200 with a body that is not JSON"),
        (json_reply(200, {"detail": "ok"}), "200 with a body that is not a list of objects"),
        (json_reply(200, [1, 2]), "200 with a body that is not a list of objects"),
    ],
)
@pytest.mark.anyio
async def test_a_non_retryable_failure_fails_at_once_and_names_the_request(
    reply: httpx2.Response, reason: str
) -> None:
    server, sleeps = Server([reply]), Sleeps()

    with pytest.raises(OpenF1Error) as failure:
        await fetch(LAPS, server, sleeps)

    assert str(failure.value).startswith(f"GET /laps?session_key=9472 -> {reason}")
    assert failure.value.request == LAPS
    assert len(server.requests) == 1
    assert sleeps.seconds == []


@pytest.mark.parametrize(
    "transient",
    [
        json_reply(429, {"detail": "Too Many Requests"}),
        json_reply(500, {}),
        json_reply(502, {}),
        json_reply(503, {}),
        json_reply(504, {}),
        httpx2.ConnectError("connection refused"),
        httpx2.ReadTimeout("read timed out"),
    ],
)
@pytest.mark.anyio
async def test_a_transient_failure_is_retried_with_backoff(transient: Reply) -> None:
    server, sleeps = Server([transient, transient, json_reply(200, ROWS)]), Sleeps()

    response = await fetch(LAPS, server, sleeps)

    assert response.rows == ROWS
    assert len(server.requests) == 3
    assert sleeps.seconds == [1.0, 2.0]


@pytest.mark.parametrize(
    ("transient", "reason"),
    [
        (json_reply(503, {"detail": "down"}), '503 {"detail":"down"}'),
        (httpx2.ConnectError("connection refused"), "ConnectError: connection refused"),
    ],
)
@pytest.mark.anyio
async def test_retries_stop_at_the_attempt_limit(transient: Reply, reason: str) -> None:
    server, sleeps = Server([transient]), Sleeps()

    with pytest.raises(OpenF1Error, match=f"-> {reason}"):
        await fetch(LAPS, server, sleeps, max_attempts=4)

    assert len(server.requests) == 4
    assert sleeps.seconds == [1.0, 2.0, 4.0]


@pytest.mark.anyio
async def test_every_attempt_goes_through_the_rate_limiter() -> None:
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter([RateLimit(1, 1.0)], clock=clock, sleep=clock.sleep)
    server = Server([json_reply(503, {}), json_reply(200, ROWS)])
    async with httpx2.AsyncClient(
        base_url=BASE_URL, transport=httpx2.MockTransport(server)
    ) as http:
        client = OpenF1Client(http, limiter, RetryPolicy(3, 0.25), sleep=clock.sleep)
        await client.fetch(LAPS)

    assert len(server.requests) == 2
    assert clock.slept_s == [0.25, 0.75]


def test_a_retry_policy_needs_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="max_attempts must be at least 1, got 0"):
        RetryPolicy(0, 1.0)
