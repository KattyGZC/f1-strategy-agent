from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from f1_strategy.adapters.http import health, replays, sessions
from f1_strategy.adapters.http.services import ApiServices, api_services
from f1_strategy.adapters.settings import ApiSettings
from f1_strategy.application.replay import (
    LapNotFoundError,
    ReplayFailedError,
    ReplayNotFoundError,
    SessionNotLoadedError,
    TooManyReplaysError,
)

type ServicesFactory = Callable[[], AbstractAsyncContextManager[ApiServices]]

ERROR_STATUS: dict[type[Exception], int] = {
    LapNotFoundError: status.HTTP_404_NOT_FOUND,
    ReplayFailedError: status.HTTP_409_CONFLICT,
    ReplayNotFoundError: status.HTTP_404_NOT_FOUND,
    SessionNotLoadedError: status.HTTP_404_NOT_FOUND,
    TooManyReplaysError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def services_from_settings() -> AbstractAsyncContextManager[ApiServices]:
    return api_services(ApiSettings())


def create_app(services: ServicesFactory = services_from_settings) -> FastAPI:
    """The API. Its services open with the app's lifespan, so building it, as the
    OpenAPI export does, reads no settings and connects to nothing."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with services() as running:
            app.state.services = running
            yield

    app = FastAPI(title="F1 Strategy Agent", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router, prefix="/api")
    app.include_router(replays.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    for error, code in ERROR_STATUS.items():
        app.add_exception_handler(error, _status_handler(code))
    return app


def _status_handler(code: int) -> Callable[[Request, Exception], JSONResponse]:
    def handle(_: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=code)

    return handle
