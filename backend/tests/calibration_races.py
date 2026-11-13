"""Clean rows of four 2024 races, to calibrate the lap-time model on real data.

Exported on 2026-11-12 from the local clean model (`TRANSFORM_VERSION` 1, `make transform
YEAR=2024`) with one `SELECT` of every column per table and session: lap, stint, pit,
race_control and weather of Bahrain 9472, Canada 9531, Spain 9539 and Britain 9558.
"""

import json
from datetime import datetime
from decimal import Decimal
from functools import cache
from pathlib import Path

from f1_strategy.domain.clean import (
    Compound,
    Flag,
    FlagScope,
    Lap,
    Pit,
    RaceControl,
    RaceControlCategory,
    Stint,
    Weather,
)
from tests.replay_rows import Rows

FIXTURE = Path(__file__).parent / "fixtures" / "clean_2024_calibration_races.json"
BAHRAIN, CANADA, SPAIN, BRITAIN = 9472, 9531, 9539, 9558

type _Row = list[object]


def race(session_key: int) -> Rows:
    tables = _fixture()[str(session_key)]
    return Rows(
        laps=[_lap(row) for row in tables["laps"]],
        stints=[_stint(row) for row in tables["stints"]],
        pits=[_pit(row) for row in tables["pits"]],
        race_control=[_race_control(row) for row in tables["race_control"]],
        weather=[_weather(row) for row in tables["weather"]],
    )


@cache
def _fixture() -> dict[str, dict[str, list[_Row]]]:
    data: dict[str, dict[str, list[_Row]]] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def _lap(row: _Row) -> Lap:
    session_key, driver, lap_number, start, duration, s1, s2, s3, i1, i2, st, out = row
    return Lap(
        _int(session_key), _int(driver), _int(lap_number), _instant(start), _number(duration),
        _number(s1), _number(s2), _number(s3), _optional_int(i1), _optional_int(i2),
        _optional_int(st), is_pit_out_lap=out is True,
    )  # fmt: skip


def _stint(row: _Row) -> Stint:
    session_key, driver, number, compound, lap_start, lap_end, age = row
    return Stint(
        _int(session_key), _int(driver), _int(number), Compound(str(compound)),
        _optional_int(lap_start), _optional_int(lap_end), _int(age),
    )  # fmt: skip


def _pit(row: _Row) -> Pit:
    session_key, driver, lap_number, date, lane, stop = row
    return Pit(
        _int(session_key), _int(driver), _int(lap_number), _required_instant(date),
        _number(lane), _number(stop),
    )  # fmt: skip


def _race_control(row: _Row) -> RaceControl:
    session_key, seq, date, category, flag, scope, sector, driver, lap, phase, message = row
    return RaceControl(
        _int(session_key), _int(seq), _required_instant(date), RaceControlCategory(str(category)),
        None if flag is None else Flag(str(flag)), None if scope is None else FlagScope(str(scope)),
        _optional_int(sector), _optional_int(driver), _optional_int(lap), _optional_int(phase),
        str(message),
    )  # fmt: skip


def _weather(row: _Row) -> Weather:
    session_key, date, air, track, humidity, pressure, rain, wind, direction = row
    return Weather(
        _int(session_key), _required_instant(date), Decimal(str(air)), Decimal(str(track)),
        Decimal(str(humidity)), Decimal(str(pressure)), rainfall=rain is True,
        wind_speed=Decimal(str(wind)), wind_direction=_int(direction),
    )  # fmt: skip


def _int(value: object) -> int:
    assert isinstance(value, int)
    return value


def _optional_int(value: object) -> int | None:
    return None if value is None else _int(value)


def _number(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _instant(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def _required_instant(value: object) -> datetime:
    return datetime.fromisoformat(str(value))
