from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from src.core.entities.lap import LapCreate
from src.infrastructure.database.models import Lap


def session_laps_exist(db: Session, session_key: int) -> bool:
    return db.scalar(select(exists().where(Lap.session_key == session_key))) or False


def bulk_insert_laps(db: Session, laps: list[LapCreate]) -> int:
    if not laps:
        return 0

    db.bulk_insert_mappings(Lap, [lap.model_dump() for lap in laps])
    db.commit()
    return len(laps)
