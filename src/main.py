from fastapi import FastAPI

from src.api.routes.health import router as health_router
from src.infrastructure.database import models  # noqa: F401 - Registra los modelos en Base

app = FastAPI(title="F1 Strategy Agent", version="0.1.0")

app.include_router(health_router)
