from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.core.entities.driver import DriverCreate
from src.infrastructure.database.models import Driver


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
