from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from src.core.entities.lap import LapCreate
from src.infrastructure.database.models import Lap


def get_laps_by_session(
    db: Session, session_key: int, driver_number: int | None = None
) -> list[Lap]:
    stmt = select(Lap).where(Lap.session_key == session_key).order_by(
        Lap.driver_number, Lap.lap_number
    )
    if driver_number is not None:
        stmt = stmt.where(Lap.driver_number == driver_number)
    return list(db.scalars(stmt))


def session_laps_exist(db: Session, session_key: int) -> bool:
    return db.scalar(select(exists().where(Lap.session_key == session_key))) or False


def bulk_insert_laps(db: Session, laps: list[LapCreate]) -> int:
    if not laps:
        return 0

    db.bulk_insert_mappings(Lap, [lap.model_dump() for lap in laps])
    db.commit()
    return len(laps)
