from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from src.infrastructure.database.connection import Base


class Driver(Base):
    __tablename__ = "drivers"

    driver_number = Column(Integer, primary_key=True)
    full_name = Column(String(100))
    team_name = Column(String(100))
    country_code = Column(String(3), nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    session_key = Column(Integer, primary_key=True)
    session_name = Column(String(50))
    circuit_short_name = Column(String(50))
    date_start = Column(DateTime, nullable=True)
    year = Column(Integer)


class Lap(Base):
    __tablename__ = "laps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_key = Column(Integer, index=True)
    driver_number = Column(Integer, index=True)
    lap_number = Column(Integer)
    duration_ms = Column(Integer, nullable=True)
    is_pit_out_lap = Column(Boolean, default=False)
    stint = Column(Integer, nullable=True)


class Interval(Base):
    __tablename__ = "intervals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_key = Column(Integer, index=True)
    driver_number = Column(Integer, index=True)
    gap_to_leader = Column(String(20), nullable=True)
    interval = Column(String(20), nullable=True)
    date = Column(DateTime, nullable=True)


class RaceSummary(Base):
    __tablename__ = "race_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_key = Column(Integer, index=True)
    content = Column(Text)
    embedding = Column(Vector(1536), nullable=True)
