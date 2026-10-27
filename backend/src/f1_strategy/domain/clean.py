"""The clean model: one session's raw OpenF1 rows turned into typed rows (ADR 0008).

Every function here is pure. The same raw rows give the same clean rows, in the same order, and
the same content hash. Field names are the column names of the clean schema.
"""

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import astuple, dataclass, fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from _typeshed import SupportsRichComparison

from f1_strategy.domain.openf1 import (
    SESSION_ENDPOINTS,
    Endpoint,
    JsonObject,
    JsonValue,
    SessionName,
    SessionType,
)

# Raise whenever the clean rows of the same raw input change. The golden test pins it to the
# content hash of a fixed input, so a change in output without a new version fails CI.
TRANSFORM_VERSION = "1"

QUALIFYING_PHASES = 3
LAPS_BEHIND = re.compile(r"\+(\d+) LAPS?")
GMT_OFFSET = re.compile(r"(-?)(\d{2}):(\d{2}):(\d{2})")


class CircuitType(StrEnum):
    PERMANENT = "Permanent"
    STREET = "Temporary - Street"
    ROAD = "Temporary - Road"


class Compound(StrEnum):
    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    INTERMEDIATE = "INTERMEDIATE"
    WET = "WET"
    UNKNOWN = "UNKNOWN"


class RaceControlCategory(StrEnum):
    FLAG = "Flag"
    OTHER = "Other"
    SESSION_STATUS = "SessionStatus"
    DRS = "Drs"
    SAFETY_CAR = "SafetyCar"
    CAR_EVENT = "CarEvent"


class Flag(StrEnum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    DOUBLE_YELLOW = "DOUBLE YELLOW"
    RED = "RED"
    BLUE = "BLUE"
    CLEAR = "CLEAR"
    CHEQUERED = "CHEQUERED"
    BLACK_AND_WHITE = "BLACK AND WHITE"


class FlagScope(StrEnum):
    TRACK = "Track"
    SECTOR = "Sector"
    DRIVER = "Driver"


class CleanDataError(ValueError):
    """Raw data the clean model does not describe. Retrying the same input fails the same way."""

    def __init__(self, endpoint: Endpoint, row: int | None, problem: str) -> None:
        where = endpoint if row is None else f"{endpoint} row {row}"
        super().__init__(f"{where}: {problem}")
        self.endpoint = endpoint
        self.row = row


@dataclass(frozen=True)
class Meeting:
    meeting_key: int
    year: int
    meeting_name: str
    meeting_official_name: str
    circuit_key: int
    circuit_short_name: str
    circuit_type: CircuitType
    country_key: int
    country_code: str
    country_name: str
    location: str
    gmt_offset: timedelta
    date_start: datetime
    date_end: datetime
    is_cancelled: bool


@dataclass(frozen=True)
class SessionRow:
    session_key: int
    meeting_key: int
    session_type: SessionType
    session_name: SessionName
    date_start: datetime
    date_end: datetime


@dataclass(frozen=True)
class DriverSession:
    session_key: int
    driver_number: int
    full_name: str
    first_name: str
    last_name: str
    broadcast_name: str
    name_acronym: str
    country_code: str | None
    team_name: str
    team_colour: str
    headshot_url: str | None


@dataclass(frozen=True)
class Lap:
    session_key: int
    driver_number: int
    lap_number: int
    date_start: datetime | None
    lap_duration: Decimal | None
    duration_sector_1: Decimal | None
    duration_sector_2: Decimal | None
    duration_sector_3: Decimal | None
    i1_speed: int | None
    i2_speed: int | None
    st_speed: int | None
    is_pit_out_lap: bool


@dataclass(frozen=True)
class Stint:
    session_key: int
    driver_number: int
    stint_number: int
    compound: Compound
    lap_start: int | None
    lap_end: int | None
    tyre_age_at_start: int


@dataclass(frozen=True)
class Pit:
    session_key: int
    driver_number: int
    lap_number: int
    date: datetime
    lane_duration: Decimal | None
    stop_duration: Decimal | None


@dataclass(frozen=True)
class Interval:
    session_key: int
    driver_number: int
    date: datetime
    gap_to_leader_s: Decimal | None
    gap_to_leader_laps: int | None
    interval_s: Decimal | None
    interval_laps: int | None


@dataclass(frozen=True)
class Position:
    session_key: int
    driver_number: int
    date: datetime
    position: int


@dataclass(frozen=True)
class RaceControl:
    session_key: int
    seq: int
    date: datetime
    category: RaceControlCategory
    flag: Flag | None
    scope: FlagScope | None
    sector: int | None
    driver_number: int | None
    lap_number: int | None
    qualifying_phase: int | None
    message: str


@dataclass(frozen=True)
class Weather:
    session_key: int
    date: datetime
    air_temperature: Decimal
    track_temperature: Decimal
    humidity: Decimal
    pressure: Decimal
    rainfall: bool
    wind_speed: Decimal
    wind_direction: int


@dataclass(frozen=True)
class SessionResult:
    session_key: int
    driver_number: int
    position: int | None
    number_of_laps: int | None
    dnf: bool
    dns: bool
    dsq: bool
    duration: Decimal | None
    gap_to_leader_s: Decimal | None
    gap_to_leader_laps: int | None
    points: Decimal | None


@dataclass(frozen=True)
class QualifyingPhaseResult:
    session_key: int
    driver_number: int
    phase: int
    duration: Decimal | None
    gap_to_leader_s: Decimal | None


@dataclass(frozen=True)
class StartingGrid:
    session_key: int
    driver_number: int
    position: int
    lap_duration: Decimal | None


@dataclass(frozen=True)
class Overtake:
    session_key: int
    date: datetime
    overtaking_driver_number: int
    overtaken_driver_number: int
    position: int


@dataclass(frozen=True)
class TeamRadio:
    session_key: int
    driver_number: int
    date: datetime
    recording_url: str


type CleanRow = (
    DriverSession
    | Lap
    | Stint
    | Pit
    | Interval
    | Position
    | RaceControl
    | Weather
    | SessionResult
    | QualifyingPhaseResult
    | StartingGrid
    | Overtake
    | TeamRadio
)


type CleanRecord = Meeting | SessionRow | CleanRow


@dataclass(frozen=True)
class RawSession:
    """The raw input of one session: its index row, its meeting's row, and each endpoint's rows."""

    session: JsonObject
    meeting: JsonObject
    rows: Mapping[Endpoint, Sequence[JsonObject]]


@dataclass(frozen=True)
class CleanSession:
    meeting: Meeting
    session: SessionRow
    drivers: tuple[DriverSession, ...]
    laps: tuple[Lap, ...]
    stints: tuple[Stint, ...]
    pits: tuple[Pit, ...]
    intervals: tuple[Interval, ...]
    positions: tuple[Position, ...]
    race_control: tuple[RaceControl, ...]
    weather: tuple[Weather, ...]
    results: tuple[SessionResult, ...]
    qualifying_phases: tuple[QualifyingPhaseResult, ...]
    starting_grid: tuple[StartingGrid, ...]
    overtakes: tuple[Overtake, ...]
    team_radio: tuple[TeamRadio, ...]

    def tables(self) -> tuple[tuple[str, tuple[CleanRow, ...]], ...]:
        """The session's own rows by table, parents before children, as they are written."""
        return (
            ("driver_session", self.drivers),
            ("lap", self.laps),
            ("stint", self.stints),
            ("pit", self.pits),
            ("interval", self.intervals),
            ("position", self.positions),
            ("race_control", self.race_control),
            ("weather", self.weather),
            ("session_result", self.results),
            ("qualifying_phase_result", self.qualifying_phases),
            ("starting_grid", self.starting_grid),
            ("overtake", self.overtakes),
            ("team_radio", self.team_radio),
        )


def clean_session(raw: RawSession) -> CleanSession:
    meeting = _meeting(_Reader(raw.meeting, Endpoint.MEETINGS, None))
    session = _session(_Reader(raw.session, Endpoint.SESSIONS, None), meeting)
    expected = SESSION_ENDPOINTS[session.session_type]
    for endpoint, rows in raw.rows.items():
        if rows and endpoint not in expected:
            raise CleanDataError(endpoint, None, f"not an endpoint of a {session.session_type}")

    def parse[T](endpoint: Endpoint, parse_row: Callable[["_Reader"], T]) -> list[T]:
        return [
            parse_row(_Reader(row, endpoint, index, session.session_key))
            for index, row in enumerate(raw.rows.get(endpoint, ()))
        ]

    results, phases = _results(parse(Endpoint.SESSION_RESULT, _ResultParts.read), session)
    stints = _sorted(Endpoint.STINTS, parse(Endpoint.STINTS, _stint), _driver_stint)
    _check_consecutive_stints(stints)
    return CleanSession(
        meeting=meeting,
        session=session,
        drivers=_sorted(Endpoint.DRIVERS, parse(Endpoint.DRIVERS, _driver), _driver_key),
        laps=_sorted(Endpoint.LAPS, parse(Endpoint.LAPS, _lap), _driver_lap),
        stints=stints,
        pits=_sorted(Endpoint.PIT, parse(Endpoint.PIT, _pit), _driver_lap),
        intervals=_sorted(Endpoint.INTERVALS, parse(Endpoint.INTERVALS, _interval), _driver_date),
        positions=_sorted(Endpoint.POSITION, parse(Endpoint.POSITION, _position), _driver_date),
        race_control=tuple(
            _race_control(_Reader(row, Endpoint.RACE_CONTROL, seq, session.session_key), seq)
            for seq, row in enumerate(raw.rows.get(Endpoint.RACE_CONTROL, ()))
        ),
        weather=_sorted(Endpoint.WEATHER, parse(Endpoint.WEATHER, _weather), _date),
        results=_sorted(Endpoint.SESSION_RESULT, results, _driver_key),
        qualifying_phases=_sorted(Endpoint.SESSION_RESULT, phases, _driver_phase),
        starting_grid=_sorted(
            Endpoint.STARTING_GRID, parse(Endpoint.STARTING_GRID, _grid), _driver_key
        ),
        overtakes=_sorted(Endpoint.OVERTAKES, parse(Endpoint.OVERTAKES, _overtake), _overtake_key),
        team_radio=_sorted(Endpoint.TEAM_RADIO, parse(Endpoint.TEAM_RADIO, _radio), _driver_date),
    )


def content_hash(clean: CleanSession) -> str:
    """SHA-256 of every row of the session in table and key order; equal rows, equal hash."""
    digest = hashlib.sha256()
    tables: tuple[tuple[str, Sequence[CleanRecord]], ...] = (
        ("meeting", (clean.meeting,)),
        ("session", (clean.session,)),
        *clean.tables(),
    )
    for table, rows in tables:
        for row in rows:
            line = json.dumps([table, [_canonical(value) for value in astuple(row)]])
            digest.update(line.encode())
            digest.update(b"\n")
    return digest.hexdigest()


def input_fingerprint(
    session: JsonObject, meeting: JsonObject, documents: Iterable[tuple[str, datetime]]
) -> str:
    """SHA-256 of what a session is built from: the content of its index and meeting rows, and
    the request key and fetch time of each of its own documents. The season index and the
    calendar are stored again every hour of a season in progress, so their identity would
    change the fingerprint of every session; only the session's rows in them count."""
    lines = sorted(
        {f"{key} {fetched_at.astimezone(UTC).isoformat()}" for key, fetched_at in documents}
    )
    context = [json.dumps(row, sort_keys=True) for row in (session, meeting)]
    return hashlib.sha256("\n".join([*context, *lines]).encode()).hexdigest()


def column_names(row_type: type[CleanRecord]) -> tuple[str, ...]:
    return tuple(field.name for field in fields(row_type))


def _canonical(value: object) -> object:
    if isinstance(value, Decimal | datetime | timedelta):
        return str(value)
    return value


class _Reader:
    """Typed access to one raw row; every failure names the endpoint and the row."""

    def __init__(
        self, row: JsonObject, endpoint: Endpoint, index: int | None, session_key: int | None = None
    ) -> None:
        self._row = row
        self._endpoint = endpoint
        self._index = index
        if session_key is not None and self.integer("session_key") != session_key:
            self.fail(f"session_key {row.get('session_key')!r} is not {session_key}")

    def fail(self, problem: str) -> NoReturn:
        raise CleanDataError(self._endpoint, self._index, problem)

    def value(self, name: str) -> JsonValue:
        if name not in self._row:
            self.fail(f"{name} is missing")
        return self._row[name]

    def has(self, name: str) -> bool:
        return name in self._row

    def integer(self, name: str) -> int:
        value = self.opt_integer(name)
        return value if value is not None else self._null(name)

    def opt_integer(self, name: str) -> int | None:
        value = self.value(name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            self.fail(f"{name} must be an integer, got {value!r}")
        return value

    def text(self, name: str) -> str:
        value = self.opt_text(name)
        return value if value is not None else self._null(name)

    def opt_text(self, name: str) -> str | None:
        value = self.value(name)
        if value is not None and not isinstance(value, str):
            self.fail(f"{name} must be a string, got {value!r}")
        return value

    def boolean(self, name: str) -> bool:
        value = self.value(name)
        if not isinstance(value, bool):
            self.fail(f"{name} must be a boolean, got {value!r}")
        return value

    def decimal(self, name: str) -> Decimal:
        value = self.opt_decimal(name)
        return value if value is not None else self._null(name)

    def opt_decimal(self, name: str) -> Decimal | None:
        return self.to_decimal(name, self.value(name))

    def to_decimal(self, name: str, value: JsonValue) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            self.fail(f"{name} must be a number, got {value!r}")
        # repr is the shortest text that reads back as the same float: 91.234, not 91.2339999...
        return Decimal(repr(value)) if isinstance(value, float) else Decimal(value)

    def utc(self, name: str) -> datetime:
        value = self.opt_utc(name)
        return value if value is not None else self._null(name)

    def opt_utc(self, name: str) -> datetime | None:
        raw = self.opt_text(name)
        if raw is None:
            return None
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            self.fail(f"{name} is not an ISO timestamp: {raw!r}")
        if value.utcoffset() is None:
            self.fail(f"{name} has no timezone: {raw!r}")
        return value.astimezone(UTC)

    def enum[E: StrEnum](self, name: str, closed_set: type[E]) -> E:
        value = self.opt_enum(name, closed_set)
        return value if value is not None else self._null(name)

    def opt_enum[E: StrEnum](self, name: str, closed_set: type[E]) -> E | None:
        raw = self.opt_text(name)
        if raw is None:
            return None
        try:
            return closed_set(raw)
        except ValueError:
            self.fail(f"{name} {raw!r} is not one of {[member.value for member in closed_set]}")

    def gap(self, name: str) -> tuple[Decimal | None, int | None]:
        """A gap in seconds, or in laps when OpenF1 writes "+N LAP(S)"; at most one is set."""
        value = self.value(name)
        if isinstance(value, str):
            match = LAPS_BEHIND.fullmatch(value)
            if match is None:
                self.fail(f"{name} {value!r} is neither seconds nor laps behind")
            return None, int(match.group(1))
        return self.to_decimal(name, value), None

    def _null(self, name: str) -> NoReturn:
        self.fail(f"{name} is null")


def _meeting(row: _Reader) -> Meeting:
    raw_offset = row.text("gmt_offset")
    offset = GMT_OFFSET.fullmatch(raw_offset)
    if offset is None:
        row.fail(f"gmt_offset {raw_offset!r} is not [-]HH:MM:SS")
    sign, hours, minutes, seconds = offset.groups()
    magnitude = timedelta(hours=int(hours), minutes=int(minutes), seconds=int(seconds))
    return Meeting(
        meeting_key=row.integer("meeting_key"),
        year=row.integer("year"),
        meeting_name=row.text("meeting_name"),
        meeting_official_name=row.text("meeting_official_name"),
        circuit_key=row.integer("circuit_key"),
        circuit_short_name=row.text("circuit_short_name"),
        circuit_type=row.enum("circuit_type", CircuitType),
        country_key=row.integer("country_key"),
        country_code=row.text("country_code"),
        country_name=row.text("country_name"),
        location=row.text("location"),
        gmt_offset=-magnitude if sign else magnitude,
        date_start=row.utc("date_start"),
        date_end=row.utc("date_end"),
        is_cancelled=row.boolean("is_cancelled"),
    )


def _session(row: _Reader, meeting: Meeting) -> SessionRow:
    if row.boolean("is_cancelled"):
        row.fail("the session is cancelled")
    session = SessionRow(
        session_key=row.integer("session_key"),
        meeting_key=row.integer("meeting_key"),
        session_type=row.enum("session_type", SessionType),
        session_name=row.enum("session_name", SessionName),
        date_start=row.utc("date_start"),
        date_end=row.utc("date_end"),
    )
    if session.meeting_key != meeting.meeting_key:
        row.fail(f"meeting_key {session.meeting_key} is not the meeting's {meeting.meeting_key}")
    return session


def _driver(row: _Reader) -> DriverSession:
    return DriverSession(
        session_key=row.integer("session_key"),
        driver_number=row.integer("driver_number"),
        full_name=row.text("full_name"),
        first_name=row.text("first_name"),
        last_name=row.text("last_name"),
        broadcast_name=row.text("broadcast_name"),
        name_acronym=row.text("name_acronym"),
        country_code=row.opt_text("country_code"),
        team_name=row.text("team_name"),
        team_colour=row.text("team_colour"),
        headshot_url=row.opt_text("headshot_url"),
    )


def _lap(row: _Reader) -> Lap:
    return Lap(
        session_key=row.integer("session_key"),
        driver_number=row.integer("driver_number"),
        lap_number=row.integer("lap_number"),
        date_start=row.opt_utc("date_start"),
        lap_duration=row.opt_decimal("lap_duration"),
        duration_sector_1=row.opt_decimal("duration_sector_1"),
        duration_sector_2=row.opt_decimal("duration_sector_2"),
        duration_sector_3=row.opt_decimal("duration_sector_3"),
        i1_speed=row.opt_integer("i1_speed"),
        i2_speed=row.opt_integer("i2_speed"),
        st_speed=row.opt_integer("st_speed"),
        is_pit_out_lap=row.boolean("is_pit_out_lap"),
    )


def _stint(row: _Reader) -> Stint:
    return Stint(
        session_key=row.integer("session_key"),
        driver_number=row.integer("driver_number"),
        stint_number=row.integer("stint_number"),
        compound=row.enum("compound", Compound),
        lap_start=row.opt_integer("lap_start"),
        lap_end=row.opt_integer("lap_end"),
        tyre_age_at_start=row.integer("tyre_age_at_start"),
    )


def _pit(row: _Reader) -> Pit:
    lane_duration = row.opt_decimal("lane_duration")
    # Only lane_duration is stored; the two were equal in every 2024 pit stop. If they ever
    # differ, a value would be dropped silently, so the session fails instead.
    if row.opt_decimal("pit_duration") != lane_duration:
        row.fail("pit_duration differs from lane_duration")
    return Pit(
        session_key=row.integer("session_key"),
        driver_number=row.integer("driver_number"),
        lap_number=row.integer("lap_number"),
        date=row.utc("date"),
        lane_duration=lane_duration,
        stop_duration=row.opt_decimal("stop_duration"),
    )


def _interval(row: _Reader) -> Interval:
    gap_s, gap_laps = row.gap("gap_to_leader")
    interval_s, interval_laps = row.gap("interval")
    return Interval(
        session_key=row.integer("session_key"),
        driver_number=row.integer("driver_number"),
        date=row.utc("date"),
        gap_to_leader_s=gap_s,
        gap_to_leader_laps=gap_laps,
        interval_s=interval_s,
        interval_laps=interval_laps,
    )


def _position(row: _Reader) -> Position:
    return Position(
        session_key=row.integer("session_key"),
        driver_number=row.integer("driver_number"),
        date=row.utc("date"),
        position=row.integer("position"),
    )


def _race_control(row: _Reader, seq: int) -> RaceControl:
    # No natural key: several messages share an instant. The row's position in its raw document
    # is the key, stable because raw documents are never rewritten (ADR 0004).
    return RaceControl(
        session_key=row.integer("session_key"),
        seq=seq,
        date=row.utc("date"),
        category=row.enum("category", RaceControlCategory),
        flag=row.opt_enum("flag", Flag),
        scope=row.opt_enum("scope", FlagScope),
        sector=row.opt_integer("sector"),
        driver_number=row.opt_integer("driver_number"),
        lap_number=row.opt_integer("lap_number"),
        qualifying_phase=row.opt_integer("qualifying_phase"),
        message=row.text("message"),
    )


def _weather(row: _Reader) -> Weather:
    rainfall = row.integer("rainfall")
    if rainfall not in (0, 1):
        row.fail(f"rainfall must be 0 or 1, got {rainfall}")
    return Weather(
        session_key=row.integer("session_key"),
        date=row.utc("date"),
        air_temperature=row.decimal("air_temperature"),
        track_temperature=row.decimal("track_temperature"),
        humidity=row.decimal("humidity"),
        pressure=row.decimal("pressure"),
        rainfall=rainfall == 1,
        wind_speed=row.decimal("wind_speed"),
        wind_direction=row.integer("wind_direction"),
    )


@dataclass(frozen=True)
class _ResultParts:
    """A session_result row before the session type decides between scalars and Q1-Q3 lists."""

    row: _Reader
    duration: JsonValue
    gap: JsonValue

    @classmethod
    def read(cls, row: _Reader) -> "_ResultParts":
        return cls(row, row.value("duration"), row.value("gap_to_leader"))


def _results(
    parts: list[_ResultParts], session: SessionRow
) -> tuple[list[SessionResult], list[QualifyingPhaseResult]]:
    results: list[SessionResult] = []
    phases: list[QualifyingPhaseResult] = []
    qualifying = session.session_type == SessionType.QUALIFYING
    for part in parts:
        row = part.row
        if qualifying:
            phases.extend(_phases(part))
            duration, gap_s, gap_laps, points = None, None, None, None
            if row.has("points"):
                row.fail("a qualifying result has points")
        else:
            duration = row.opt_decimal("duration")
            gap_s, gap_laps = row.gap("gap_to_leader")
            points = row.decimal("points")
        results.append(
            SessionResult(
                session_key=row.integer("session_key"),
                driver_number=row.integer("driver_number"),
                position=row.opt_integer("position"),
                number_of_laps=row.opt_integer("number_of_laps"),
                dnf=row.boolean("dnf"),
                dns=row.boolean("dns"),
                dsq=row.boolean("dsq"),
                duration=duration,
                gap_to_leader_s=gap_s,
                gap_to_leader_laps=gap_laps,
                points=points,
            )
        )
    return results, phases


def _phases(part: _ResultParts) -> list[QualifyingPhaseResult]:
    row = part.row
    durations = _per_phase(row, "duration", part.duration)
    gaps = _per_phase(row, "gap_to_leader", part.gap)
    return [
        QualifyingPhaseResult(
            session_key=row.integer("session_key"),
            driver_number=row.integer("driver_number"),
            phase=phase,
            duration=row.to_decimal("duration", duration),
            gap_to_leader_s=row.to_decimal("gap_to_leader", gap),
        )
        for phase, (duration, gap) in enumerate(zip(durations, gaps, strict=True), 1)
    ]


def _per_phase(row: _Reader, name: str, value: JsonValue) -> list[JsonValue]:
    if not isinstance(value, list) or len(value) != QUALIFYING_PHASES:
        row.fail(f"{name} of a qualifying result must be a list of three, got {value!r}")
    return value


def _grid(row: _Reader) -> StartingGrid:
    return StartingGrid(
        session_key=row.integer("session_key"),
        driver_number=row.integer("driver_number"),
        position=row.integer("position"),
        lap_duration=row.opt_decimal("lap_duration"),
    )


def _overtake(row: _Reader) -> Overtake:
    return Overtake(
        session_key=row.integer("session_key"),
        date=row.utc("date"),
        overtaking_driver_number=row.integer("overtaking_driver_number"),
        overtaken_driver_number=row.integer("overtaken_driver_number"),
        position=row.integer("position"),
    )


def _radio(row: _Reader) -> TeamRadio:
    return TeamRadio(
        session_key=row.integer("session_key"),
        driver_number=row.integer("driver_number"),
        date=row.utc("date"),
        recording_url=row.text("recording_url"),
    )


def _sorted[R, K: SupportsRichComparison](
    endpoint: Endpoint, rows: list[R], key: Callable[[R], K]
) -> tuple[R, ...]:
    """Rows in key order; two rows with one key fail the session instead of picking one."""
    keyed = sorted(rows, key=key)
    for previous, current in pairwise(keyed):
        if key(previous) == key(current):
            raise CleanDataError(endpoint, None, f"two rows share the key {key(current)!r}")
    return tuple(keyed)


def _check_consecutive_stints(stints: tuple[Stint, ...]) -> None:
    """Stints are numbered 1..n per driver, and each starts on its predecessor's last lap
    (OpenF1 counts the lap of the stop in both) or on the lap after."""
    by_driver: dict[int, list[Stint]] = defaultdict(list)
    for stint in stints:
        by_driver[stint.driver_number].append(stint)
    for driver_number, driver_stints in by_driver.items():
        numbers = [stint.stint_number for stint in driver_stints]
        if numbers != list(range(1, len(numbers) + 1)):
            raise CleanDataError(
                Endpoint.STINTS, None, f"driver {driver_number} has stints numbered {numbers}"
            )
        for previous, current in pairwise(driver_stints):
            if previous.lap_end is None or current.lap_start is None:
                continue
            if current.lap_start not in (previous.lap_end, previous.lap_end + 1):
                raise CleanDataError(
                    Endpoint.STINTS,
                    None,
                    f"driver {driver_number} stint {current.stint_number} starts on lap "
                    f"{current.lap_start}, stint {previous.stint_number} ended on lap "
                    f"{previous.lap_end}",
                )


def _driver_key(row: DriverSession | SessionResult | StartingGrid) -> int:
    return row.driver_number


def _driver_lap(row: Lap | Pit) -> tuple[int, int]:
    return row.driver_number, row.lap_number


def _driver_stint(row: Stint) -> tuple[int, int]:
    return row.driver_number, row.stint_number


def _driver_date(row: Interval | Position | TeamRadio) -> tuple[int, datetime]:
    return row.driver_number, row.date


def _driver_phase(row: QualifyingPhaseResult) -> tuple[int, int]:
    return row.driver_number, row.phase


def _date(row: Weather) -> datetime:
    return row.date


def _overtake_key(row: Overtake) -> tuple[datetime, int, int]:
    return row.date, row.overtaking_driver_number, row.overtaken_driver_number
