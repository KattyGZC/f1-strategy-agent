from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DBSession

from src.core.entities.session import SessionCreate
from src.infrastructure.database.models import Session


def get_all_sessions(db: DBSession, year: int | None = None) -> list[Session]:
    stmt = select(Session).order_by(Session.date_start)
    if year is not None:
        stmt = stmt.where(Session.year == year)
    return list(db.scalars(stmt))


def get_session_by_key(db: DBSession, session_key: int) -> Session | None:
    return db.get(Session, session_key)


def upsert_sessions(db: DBSession, sessions: list[SessionCreate]) -> int:
    if not sessions:
        return 0

    stmt = insert(Session).values(
        [s.model_dump() for s in sessions]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["session_key"],
        set_={
            "session_name": stmt.excluded.session_name,
            "circuit_short_name": stmt.excluded.circuit_short_name,
            "date_start": stmt.excluded.date_start,
            "year": stmt.excluded.year,
        },
    )
    db.execute(stmt)
    db.commit()
    return len(sessions)
