from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from src.core.entities.interval import IntervalCreate
from src.infrastructure.database.models import Interval


def get_intervals_by_session(
    db: Session, session_key: int, driver_number: int | None = None
) -> list[Interval]:
    stmt = select(Interval).where(Interval.session_key == session_key).order_by(
        Interval.driver_number, Interval.date
    )
    if driver_number is not None:
        stmt = stmt.where(Interval.driver_number == driver_number)
    return list(db.scalars(stmt))


def session_intervals_exist(db: Session, session_key: int) -> bool:
    return db.scalar(select(exists().where(Interval.session_key == session_key))) or False


def bulk_insert_intervals(db: Session, intervals: list[IntervalCreate]) -> int:
    if not intervals:
        return 0

    db.bulk_insert_mappings(Interval, [i.model_dump() for i in intervals])
    db.commit()
    return len(intervals)
