import logging
from typing import Literal

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from f1_strategy.adapters.http.errors import error_response, request_id
from f1_strategy.adapters.http.responses import ErrorCode, ErrorResponse
from f1_strategy.adapters.http.services import Services
from f1_strategy.adapters.observability import log_fields
from f1_strategy.application.readiness import Dependency, Readiness

router = APIRouter(tags=["health"])
logger = logging.getLogger("f1_strategy.http")

type DependencyState = Literal["ok", "failed"]


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready"]
    dependencies: dict[Dependency, DependencyState]


class NotReadyResponse(ErrorResponse):
    dependencies: dict[Dependency, DependencyState]


@router.get("/health")
async def read_health() -> HealthResponse:
    """Liveness: the process answers."""
    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": NotReadyResponse}},
)
async def read_readiness(request: Request, services: Services) -> ReadyResponse | JSONResponse:
    """Readiness: PostgreSQL and Redis answer within the configured timeout."""
    readiness = await services.readiness()
    dependencies = _states(readiness)
    if readiness.ready:
        return ReadyResponse(status="ready", dependencies=dependencies)
    for check in readiness.checks:
        if not check.ok:
            fields = log_fields(dependency=check.dependency, error=check.error)
            logger.warning("dependency_unavailable", extra=fields)
    failed = ", ".join(check.dependency for check in readiness.checks if not check.ok)
    body = NotReadyResponse(
        detail=f"not answering: {failed}",
        code=ErrorCode.NOT_READY,
        request_id=request_id(),
        dependencies=dependencies,
    )
    return error_response(request, status.HTTP_503_SERVICE_UNAVAILABLE, body)


def _states(readiness: Readiness) -> dict[Dependency, DependencyState]:
    return {check.dependency: "ok" if check.ok else "failed" for check in readiness.checks}
