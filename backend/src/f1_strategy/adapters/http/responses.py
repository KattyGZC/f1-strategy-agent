"""Error responses the routes declare in the OpenAPI schema: one shape for every error, with a
closed code a client and a log search branch on (ADR 0016)."""

from enum import StrEnum
from typing import Any

from fastapi import status
from pydantic import BaseModel


class ErrorCode(StrEnum):
    REPLAY_NOT_FOUND = "replay_not_found"
    SESSION_NOT_LOADED = "session_not_loaded"
    LAP_NOT_FOUND = "lap_not_found"
    REPLAY_FAILED = "replay_failed"
    TOO_MANY_REPLAYS = "too_many_replays"
    INVALID_REQUEST = "invalid_request"
    ROUTE_NOT_FOUND = "route_not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    NOT_READY = "not_ready"
    INTERNAL_ERROR = "internal_error"
    # For the edge to answer in the same shape (ADR 0016).
    PAYLOAD_TOO_LARGE = "payload_too_large"
    RATE_LIMITED = "rate_limited"


class ErrorResponse(BaseModel):
    detail: str
    code: ErrorCode
    request_id: str


class InvalidField(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class InvalidRequestResponse(ErrorResponse):
    errors: list[InvalidField]


# FastAPI types `responses` with Any values; a narrower type is rejected by its signature.
type Responses = dict[int | str, dict[str, Any]]
NOT_FOUND: Responses = {status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}}
CONFLICT: Responses = {status.HTTP_409_CONFLICT: {"model": ErrorResponse}}
UNAVAILABLE: Responses = {status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse}}
# Declared by every route that takes input, in place of FastAPI's own validation error shape.
INVALID: Responses = {status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": InvalidRequestResponse}}
# Every route can answer it.
EVERY_ROUTE: Responses = {status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse}}
