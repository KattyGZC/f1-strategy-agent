from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from src.core.entities.interval import IntervalCreate
from src.infrastructure.database.models import Interval


def session_intervals_exist(db: Session, session_key: int) -> bool:
    return db.scalar(select(exists().where(Interval.session_key == session_key))) or False


def bulk_insert_intervals(db: Session, intervals: list[IntervalCreate]) -> int:
    if not intervals:
        return 0

    db.bulk_insert_mappings(Interval, [i.model_dump() for i in intervals])
    db.commit()
    return len(intervals)
