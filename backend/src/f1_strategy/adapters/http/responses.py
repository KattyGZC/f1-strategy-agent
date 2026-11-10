"""Error responses the routes declare in the OpenAPI schema."""

from typing import Any

from fastapi import status
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str


# FastAPI types `responses` with Any values; a narrower type is rejected by its signature.
type Responses = dict[int | str, dict[str, Any]]
NOT_FOUND: Responses = {status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}}
UNAVAILABLE: Responses = {status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse}}
