from fastapi import FastAPI

from f1_strategy.adapters.http import health


def create_app() -> FastAPI:
    app = FastAPI(title="F1 Strategy Agent", version="0.1.0")
    app.include_router(health.router, prefix="/api")
    return app
