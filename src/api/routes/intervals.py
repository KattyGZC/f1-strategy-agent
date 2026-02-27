from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.core.entities.interval import IntervalResponse
from src.infrastructure.database.repositories.interval_repo import (
    get_intervals_by_session,
)

router = APIRouter(prefix="/intervals", tags=["intervals"])


@router.get("/{session_key}", response_model=list[IntervalResponse])
def list_intervals(
    session_key: int,
    driver_number: int | None = None,
    db: Session = Depends(get_db),
):
    """List intervals for a session."""
    return get_intervals_by_session(db, session_key, driver_number=driver_number)
