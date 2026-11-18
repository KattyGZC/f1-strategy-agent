"""Every error the API answers, in one shape with the request's id (ADR 0016)."""

from collections.abc import Callable

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic_core import ErrorDetails
from starlette.exceptions import HTTPException

from f1_strategy.adapters.http.responses import (
    ErrorCode,
    ErrorResponse,
    InvalidField,
    InvalidRequestResponse,
)
from f1_strategy.adapters.observability import current_request_id
from f1_strategy.application.replay import (
    LapNotFoundError,
    ReplayFailedError,
    ReplayNotFoundError,
    SessionNotLoadedError,
    TooManyReplaysError,
)
from f1_strategy.application.simulation import RaceNotCalibratedError
from f1_strategy.domain.strategy import DriverNotCalibratedError

type Handler = Callable[[Request, Exception], JSONResponse]

# Where a handler leaves the error code for the request middleware's log line.
ERROR_CODE_STATE = "error_code"

USE_CASE_ERRORS: dict[type[Exception], tuple[int, ErrorCode]] = {
    DriverNotCalibratedError: (status.HTTP_404_NOT_FOUND, ErrorCode.DRIVER_NOT_CALIBRATED),
    LapNotFoundError: (status.HTTP_404_NOT_FOUND, ErrorCode.LAP_NOT_FOUND),
    RaceNotCalibratedError: (status.HTTP_404_NOT_FOUND, ErrorCode.RACE_NOT_CALIBRATED),
    ReplayFailedError: (status.HTTP_409_CONFLICT, ErrorCode.REPLAY_FAILED),
    ReplayNotFoundError: (status.HTTP_404_NOT_FOUND, ErrorCode.REPLAY_NOT_FOUND),
    SessionNotLoadedError: (status.HTTP_404_NOT_FOUND, ErrorCode.SESSION_NOT_LOADED),
    TooManyReplaysError: (status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.TOO_MANY_REPLAYS),
}
# The only HTTP errors the router raises on its own.
ROUTING_ERRORS: dict[int, tuple[ErrorCode, str]] = {
    status.HTTP_404_NOT_FOUND: (ErrorCode.ROUTE_NOT_FOUND, "no API route has this path"),
    status.HTTP_405_METHOD_NOT_ALLOWED: (
        ErrorCode.METHOD_NOT_ALLOWED,
        "this route does not accept the method",
    ),
}
INVALID_REQUEST_DETAIL = "the request does not match the API schema"
INTERNAL_ERROR_DETAIL = "the API failed on an unexpected error; the logs hold it under this id"


def request_id() -> str:
    """The id the request middleware set for this request."""
    current = current_request_id.get()
    if current is None:
        raise RuntimeError("no request id: the request middleware is not installed")
    return current


def error_body(code: ErrorCode, detail: str) -> ErrorResponse:
    return ErrorResponse(detail=detail, code=code, request_id=request_id())


def error_response(request: Request, status_code: int, body: ErrorResponse) -> JSONResponse:
    """The response, with its code kept for the request's log line."""
    request.scope.setdefault("state", {})[ERROR_CODE_STATE] = body.code
    return JSONResponse(body.model_dump(mode="json"), status_code=status_code)


def handler_for[E: Exception](
    kind: type[E], handle: Callable[[Request, E], JSONResponse]
) -> Handler:
    """A handler for `kind`, which is what Starlette calls it with; anything else is re-raised."""

    def handler(request: Request, error: Exception) -> JSONResponse:
        if not isinstance(error, kind):
            raise error
        return handle(request, error)

    return handler


def install_error_handlers(app: FastAPI) -> None:
    for error, (status_code, code) in USE_CASE_ERRORS.items():
        app.add_exception_handler(error, _use_case_handler(status_code, code))
    app.add_exception_handler(
        RequestValidationError, handler_for(RequestValidationError, _invalid_request)
    )
    app.add_exception_handler(HTTPException, handler_for(HTTPException, _routing_error))


def _use_case_handler(status_code: int, code: ErrorCode) -> Handler:
    def handle(request: Request, error: Exception) -> JSONResponse:
        return error_response(request, status_code, error_body(code, str(error)))

    return handle


def _invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
    body = InvalidRequestResponse(
        detail=INVALID_REQUEST_DETAIL,
        code=ErrorCode.INVALID_REQUEST,
        request_id=request_id(),
        errors=[_invalid_field(one) for one in error.errors()],
    )
    return error_response(request, status.HTTP_422_UNPROCESSABLE_CONTENT, body)


def _invalid_field(error: ErrorDetails) -> InvalidField:
    """Without the input: a rejected value is the client's, not ours to echo or log."""
    return InvalidField(loc=list(error["loc"]), msg=error["msg"], type=error["type"])


def _routing_error(request: Request, error: HTTPException) -> JSONResponse:
    if error.status_code not in ROUTING_ERRORS:
        raise error
    code, detail = ROUTING_ERRORS[error.status_code]
    return error_response(request, error.status_code, error_body(code, detail))
