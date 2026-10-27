import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from http import HTTPStatus

import httpx2

from f1_strategy.adapters.rate_limit import SlidingWindowRateLimiter
from f1_strategy.domain.openf1 import JsonObject, RawRequest, RawResponse
from f1_strategy.domain.retry import RetryPolicy

# OpenF1 answers an empty result with 404 and this body, not with [] (curl, 2026-10-26).
NO_RESULTS_DETAIL = "No results found."
RETRYABLE_STATUSES = frozenset(
    {
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    }
)
ERROR_BODY_PREVIEW_CHARS = 200


class OpenF1Error(Exception):
    def __init__(self, request: RawRequest, reason: str) -> None:
        super().__init__(f"GET /{request.key} -> {reason}")
        self.request = request


class OpenF1Client:
    def __init__(
        self,
        http: httpx2.AsyncClient,
        limiter: SlidingWindowRateLimiter,
        retry: RetryPolicy,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._http = http
        self._limiter = limiter
        self._retry = retry
        self._sleep = sleep
        self._clock = clock

    async def fetch(self, request: RawRequest) -> RawResponse:
        attempt = 1
        while True:
            await self._limiter.acquire()
            outcome = await self._send(request)
            if attempt == self._retry.max_attempts or not _is_retryable(outcome):
                return RawResponse(request, _rows(request, outcome), self._clock())
            await self._sleep(self._retry.backoff_s(attempt))
            attempt += 1

    async def _send(self, request: RawRequest) -> httpx2.Response | httpx2.TransportError:
        try:
            return await self._http.get(f"/{request.endpoint}?{request.query}")
        except httpx2.TransportError as error:
            return error


def _is_retryable(outcome: httpx2.Response | httpx2.TransportError) -> bool:
    if isinstance(outcome, httpx2.TransportError):
        return True
    return outcome.status_code in RETRYABLE_STATUSES


def _rows(
    request: RawRequest, outcome: httpx2.Response | httpx2.TransportError
) -> list[JsonObject]:
    if isinstance(outcome, httpx2.TransportError):
        raise OpenF1Error(request, f"{type(outcome).__name__}: {outcome}") from outcome
    response = outcome
    if response.status_code == HTTPStatus.NOT_FOUND and _detail(response) == NO_RESULTS_DETAIL:
        return []
    if response.status_code != HTTPStatus.OK:
        preview = response.text[:ERROR_BODY_PREVIEW_CHARS]
        raise OpenF1Error(request, f"{response.status_code} {preview}")
    body = _json(request, response)
    if not isinstance(body, list) or not all(isinstance(row, dict) for row in body):
        raise OpenF1Error(request, "200 with a body that is not a list of objects")
    return body


def _detail(response: httpx2.Response) -> object:
    try:
        body: object = response.json()
    except ValueError:
        return None
    return body.get("detail") if isinstance(body, dict) else None


def _json(request: RawRequest, response: httpx2.Response) -> object:
    try:
        body: object = response.json()
    except ValueError as error:
        raise OpenF1Error(request, "200 with a body that is not JSON") from error
    return body
