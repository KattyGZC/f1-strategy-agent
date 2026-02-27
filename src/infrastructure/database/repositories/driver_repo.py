from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.core.entities.driver import DriverCreate
from src.infrastructure.database.models import Driver


def get_all_drivers(db: Session) -> list[Driver]:
    return list(db.scalars(select(Driver).order_by(Driver.driver_number)))


def get_driver_by_number(db: Session, driver_number: int) -> Driver | None:
    return db.get(Driver, driver_number)


def upsert_drivers(db: Session, drivers: list[DriverCreate]) -> int:
    if not drivers:
        return 0

    stmt = insert(Driver).values(
        [d.model_dump() for d in drivers]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["driver_number"],
        set_={
            "full_name": stmt.excluded.full_name,
            "team_name": stmt.excluded.team_name,
            "country_code": stmt.excluded.country_code,
        },
    )
    db.execute(stmt)
    db.commit()
    return len(drivers)
