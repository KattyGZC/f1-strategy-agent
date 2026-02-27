from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.core.entities.lap import LapResponse
from src.infrastructure.database.repositories.lap_repo import get_laps_by_session

router = APIRouter(prefix="/laps", tags=["laps"])


@router.get("/{session_key}", response_model=list[LapResponse])
def list_laps(
    
    session_key: int,
    driver_number: int | None = None,
    db: Session = Depends(get_db),
):
    """List laps for a session."""
    return get_laps_by_session(db, session_key, driver_number=driver_number)
