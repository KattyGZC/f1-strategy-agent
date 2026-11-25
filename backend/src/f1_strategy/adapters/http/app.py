from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from f1_strategy.adapters.http import assistant, health, races, replays, sessions, simulations
from f1_strategy.adapters.http.errors import install_error_handlers
from f1_strategy.adapters.http.responses import EVERY_ROUTE
from f1_strategy.adapters.http.services import ApiServices, api_services
from f1_strategy.adapters.http.tracing import RequestTracing
from f1_strategy.adapters.observability import configure_logging
from f1_strategy.adapters.settings import ApiSettings

type ServicesFactory = Callable[[], AbstractAsyncContextManager[ApiServices]]


def services_from_settings() -> AbstractAsyncContextManager[ApiServices]:
    return api_services(ApiSettings())


def production_app() -> FastAPI:
    """The app uvicorn serves. Its settings are read and its logging configured when uvicorn
    loads it, before uvicorn logs its own start, so every line of the process is JSON."""
    settings = ApiSettings()
    configure_logging(settings.log_level)
    return create_app(lambda: api_services(settings))


def create_app(services: ServicesFactory = services_from_settings) -> FastAPI:
    """The API. Its services open with the app's lifespan, so building it, as the
    OpenAPI export does, reads no settings and connects to nothing."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with services() as running:
            app.state.services = running
            yield

    app = FastAPI(
        title="F1 Strategy Agent", version="0.1.0", lifespan=lifespan, responses=EVERY_ROUTE
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(replays.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(races.router, prefix="/api")
    app.include_router(simulations.router, prefix="/api")
    app.include_router(assistant.router, prefix="/api")
    install_error_handlers(app)
    app.add_middleware(RequestTracing)
    return app
