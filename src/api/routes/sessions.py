from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.core.entities.session import SessionResponse
from src.infrastructure.database.repositories.session_repo import (
    get_all_sessions,
    get_session_by_key,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionResponse])
def list_sessions(year: int | None = None, db: Session = Depends(get_db)):
    """List all sessions."""
    return get_all_sessions(db, year=year)


@router.get("/{session_key}", response_model=SessionResponse)
def get_session(session_key: int, db: Session = Depends(get_db)):
    """Get a session by key."""
    session = get_session_by_key(db, session_key)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
