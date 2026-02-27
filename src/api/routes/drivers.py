from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.dependencies import get_db
from src.core.entities.driver import DriverResponse
from src.infrastructure.database.repositories.driver_repo import (
    get_all_drivers,
    get_driver_by_number,
)

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.get("", response_model=list[DriverResponse])
def list_drivers(db: Session = Depends(get_db)):
    """List all drivers."""
    return get_all_drivers(db)


@router.get("/{driver_number}", response_model=DriverResponse)
def get_driver(driver_number: int, db: Session = Depends(get_db)):
    """Get a driver by number."""
    driver = get_driver_by_number(db, driver_number)
    if driver is None:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver
