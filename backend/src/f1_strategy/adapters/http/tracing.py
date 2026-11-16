"""One id per request, on its response and its log lines, and one log line when it ends
(ADR 0016)."""

import logging
import time
from dataclasses import dataclass

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from f1_strategy.adapters.http.errors import ERROR_CODE_STATE, INTERNAL_ERROR_DETAIL
from f1_strategy.adapters.http.responses import ErrorCode, ErrorResponse
from f1_strategy.adapters.observability import current_request_id, log_fields, request_id_from

REQUEST_ID_HEADER = b"x-request-id"

logger = logging.getLogger("f1_strategy.http")


@dataclass
class _Outcome:
    status: int | None = None

    @property
    def started(self) -> bool:
        return self.status is not None


class RequestTracing:
    """Pure ASGI, so a streamed response passes through unbuffered."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        request_id = request_id_from(_header(scope, REQUEST_ID_HEADER))
        token = current_request_id.set(request_id)
        started_s = time.perf_counter()
        outcome = _Outcome()

        async def traced(message: Message) -> None:
            if message["type"] == "http.response.start":
                outcome.status = message["status"]
                headers = [*message.get("headers", []), (REQUEST_ID_HEADER, request_id.encode())]
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self._app(scope, receive, traced)
        except Exception:
            logger.exception("unhandled_error", extra=log_fields(**_where(scope)))
            if outcome.started:
                raise
            await _internal_error(scope, request_id)(scope, receive, traced)
        finally:
            elapsed_ms = round((time.perf_counter() - started_s) * 1000, 1)
            fields = {**_where(scope), "status": outcome.status, "code": _error_code(scope)}
            logger.info("request", extra=log_fields(**fields, duration_ms=elapsed_ms))
            current_request_id.reset(token)


def _header(scope: Scope, name: bytes) -> str | None:
    values = [value for key, value in scope["headers"] if key == name]
    return values[0].decode("latin-1") if values else None


def _where(scope: Scope) -> dict[str, object]:
    return {"method": scope["method"], "route": _route_template(scope)}


def _route_template(scope: Scope) -> str | None:
    """The matched route's template, never the raw path, so ids in the URL stay out of the logs.

    A route of an included router knows its path without the router's prefix; the prefix is what
    the request path holds before that path filled in with the request's parameters.
    """
    template = getattr(scope.get("route"), "path", None)
    if template is None:
        return None
    filled = template.format(**{name: str(value) for name, value in scope["path_params"].items()})
    prefix = scope["path"].removesuffix(filled) if scope["path"].endswith(filled) else ""
    return f"{prefix}{template}"


def _error_code(scope: Scope) -> str | None:
    code = scope.setdefault("state", {}).get(ERROR_CODE_STATE)
    return None if code is None else str(code)


def _internal_error(scope: Scope, request_id: str) -> JSONResponse:
    scope.setdefault("state", {})[ERROR_CODE_STATE] = ErrorCode.INTERNAL_ERROR
    body = ErrorResponse(
        detail=INTERNAL_ERROR_DETAIL, code=ErrorCode.INTERNAL_ERROR, request_id=request_id
    )
    return JSONResponse(
        body.model_dump(mode="json"), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
    )
