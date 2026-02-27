from fastapi import FastAPI

from src.api.routes.drivers import router as drivers_router
from src.api.routes.health import router as health_router
from src.api.routes.intervals import router as intervals_router
from src.api.routes.laps import router as laps_router
from src.api.routes.sessions import router as sessions_router
from src.infrastructure.database import models  # noqa: F401 - Registra los modelos en Base

app = FastAPI(title="F1 Strategy Agent", version="0.1.0")

app.include_router(health_router)
app.include_router(sessions_router)
app.include_router(drivers_router)
app.include_router(laps_router)
app.include_router(intervals_router)
