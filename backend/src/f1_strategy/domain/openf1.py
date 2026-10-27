from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from urllib.parse import quote

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, JsonValue]
type ParamValue = int | str


class Endpoint(StrEnum):
    MEETINGS = "meetings"
    SESSIONS = "sessions"
    DRIVERS = "drivers"
    LAPS = "laps"
    STINTS = "stints"
    PIT = "pit"
    INTERVALS = "intervals"
    POSITION = "position"
    RACE_CONTROL = "race_control"
    WEATHER = "weather"
    SESSION_RESULT = "session_result"
    STARTING_GRID = "starting_grid"
    OVERTAKES = "overtakes"
    TEAM_RADIO = "team_radio"
    CAR_DATA = "car_data"
    LOCATION = "location"


class SessionType(StrEnum):
    PRACTICE = "Practice"
    QUALIFYING = "Qualifying"
    RACE = "Race"


class SessionName(StrEnum):
    GRAND_PRIX = "Race"


class Param(StrEnum):
    YEAR = "year"
    SESSION_KEY = "session_key"
    SESSION_NAME = "session_name"
    DRIVER_NUMBER = "driver_number"
    DATE_FROM = "date>="
    DATE_BEFORE = "date<"
    DATE_START_BEFORE = "date_start<"
    DATE_END_BEFORE = "date_end<"


# OpenF1 decodes the whole query before reading operators, so a comparison is written
# "date>=value"; "date>==value", which an encoded key=value pair turns into, is a 500 (2026-10-26).
COMPARISON_PARAMS = frozenset(
    {Param.DATE_FROM, Param.DATE_BEFORE, Param.DATE_START_BEFORE, Param.DATE_END_BEFORE}
)


SESSION_ENDPOINTS: Mapping[SessionType, tuple[Endpoint, ...]] = {
    SessionType.PRACTICE: (
        Endpoint.DRIVERS,
        Endpoint.LAPS,
        Endpoint.STINTS,
        Endpoint.PIT,
        Endpoint.POSITION,
        Endpoint.RACE_CONTROL,
        Endpoint.WEATHER,
        Endpoint.SESSION_RESULT,
        Endpoint.TEAM_RADIO,
    ),
    SessionType.QUALIFYING: (
        Endpoint.DRIVERS,
        Endpoint.LAPS,
        Endpoint.STINTS,
        Endpoint.PIT,
        Endpoint.POSITION,
        Endpoint.RACE_CONTROL,
        Endpoint.WEATHER,
        Endpoint.SESSION_RESULT,
        Endpoint.STARTING_GRID,
        Endpoint.TEAM_RADIO,
    ),
    SessionType.RACE: (
        Endpoint.DRIVERS,
        Endpoint.LAPS,
        Endpoint.STINTS,
        Endpoint.PIT,
        Endpoint.INTERVALS,
        Endpoint.POSITION,
        Endpoint.RACE_CONTROL,
        Endpoint.WEATHER,
        Endpoint.SESSION_RESULT,
        Endpoint.OVERTAKES,
        Endpoint.TEAM_RADIO,
    ),
}

TELEMETRY_ENDPOINTS = (Endpoint.CAR_DATA, Endpoint.LOCATION)


@dataclass(frozen=True)
class RawRequest:
    endpoint: Endpoint
    params: tuple[tuple[Param, ParamValue], ...]

    @classmethod
    def of(cls, endpoint: Endpoint, params: Mapping[Param, ParamValue]) -> "RawRequest":
        return cls(endpoint, tuple(sorted(params.items())))

    @property
    def query(self) -> str:
        return "&".join(_query_term(param, value) for param, value in self.params)

    @property
    def key(self) -> str:
        return f"{self.endpoint}?{self.query}"

    @property
    def session_key(self) -> int | None:
        value = dict(self.params).get(Param.SESSION_KEY)
        return value if isinstance(value, int) else None


def _query_term(param: Param, value: ParamValue) -> str:
    separator = "" if param in COMPARISON_PARAMS else "="
    return f"{param}{separator}{quote(str(value), safe='')}"


@dataclass(frozen=True)
class RawResponse:
    request: RawRequest
    rows: list[JsonObject]
    fetched_at: datetime


@dataclass(frozen=True)
class Session:
    session_key: int
    session_type: SessionType
    date_start: datetime
    date_end: datetime
    is_cancelled: bool

    def settles_at(self, settle_time: timedelta) -> datetime:
        return self.date_end + settle_time


class OpenF1PayloadError(ValueError):
    pass


def meetings_request(year: int, cutoff: datetime) -> RawRequest:
    return RawRequest.of(
        Endpoint.MEETINGS, {Param.YEAR: year, Param.DATE_START_BEFORE: cutoff.isoformat()}
    )


def settled_cutoff(now: datetime, settle_time: timedelta) -> datetime:
    return _hour_start(now - settle_time)


def season_cutoff(year: int, now: datetime, settle_time: timedelta) -> datetime:
    season_end = datetime(year + 1, 1, 1, tzinfo=UTC)
    return min(settled_cutoff(now, settle_time), season_end)


def _hour_start(instant: datetime) -> datetime:
    return instant.replace(minute=0, second=0, microsecond=0)


def season_sessions_request(year: int, cutoff: datetime) -> RawRequest:
    return RawRequest.of(
        Endpoint.SESSIONS, {Param.YEAR: year, Param.DATE_END_BEFORE: cutoff.isoformat()}
    )


def grand_prix_request(cutoff: datetime) -> RawRequest:
    return RawRequest.of(
        Endpoint.SESSIONS,
        {Param.SESSION_NAME: SessionName.GRAND_PRIX, Param.DATE_END_BEFORE: cutoff.isoformat()},
    )


def latest_race(sessions: Sequence[Session], cutoff: datetime) -> Session | None:
    settled = [
        session
        for session in sessions
        if session.session_type == SessionType.RACE
        and not session.is_cancelled
        and session.date_end < cutoff
    ]
    return max(settled, key=lambda session: (session.date_end, session.session_key), default=None)


def session_request(session_key: int) -> RawRequest:
    return RawRequest.of(Endpoint.SESSIONS, {Param.SESSION_KEY: session_key})


def drivers_request(session_key: int) -> RawRequest:
    return RawRequest.of(Endpoint.DRIVERS, {Param.SESSION_KEY: session_key})


def session_requests(session: Session) -> tuple[RawRequest, ...]:
    return tuple(
        RawRequest.of(endpoint, {Param.SESSION_KEY: session.session_key})
        for endpoint in SESSION_ENDPOINTS[session.session_type]
    )


def telemetry_requests(
    session: Session, driver_numbers: Sequence[int], window: timedelta
) -> tuple[RawRequest, ...]:
    if window <= timedelta(0):
        raise ValueError(f"telemetry window must be positive, got {window}")
    return tuple(
        RawRequest.of(
            endpoint,
            {
                Param.SESSION_KEY: session.session_key,
                Param.DRIVER_NUMBER: driver_number,
                Param.DATE_FROM: window_start.isoformat(),
                Param.DATE_BEFORE: window_end.isoformat(),
            },
        )
        for endpoint in TELEMETRY_ENDPOINTS
        for driver_number in sorted(driver_numbers)
        for window_start, window_end in _windows(session.date_start, session.date_end, window)
    )


def _windows(start: datetime, end: datetime, window: timedelta) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    window_start = start
    while window_start < end:
        windows.append((window_start, window_start + window))
        window_start += window
    return windows


def parse_sessions(rows: Sequence[JsonObject]) -> list[Session]:
    return [_parse_session(row) for row in rows]


def parse_driver_numbers(rows: Sequence[JsonObject]) -> list[int]:
    return sorted({_int_field(row, "driver_number") for row in rows})


def _parse_session(row: JsonObject) -> Session:
    raw_type = _str_field(row, "session_type")
    try:
        session_type = SessionType(raw_type)
    except ValueError as error:
        raise OpenF1PayloadError(f"unknown session_type {raw_type!r}") from error
    return Session(
        session_key=_int_field(row, "session_key"),
        session_type=session_type,
        date_start=_utc_field(row, "date_start"),
        date_end=_utc_field(row, "date_end"),
        is_cancelled=_bool_field(row, "is_cancelled"),
    )


def _int_field(row: JsonObject, name: str) -> int:
    value = row.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise OpenF1PayloadError(f"{name} must be an integer, got {value!r}")
    return value


def _str_field(row: JsonObject, name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str):
        raise OpenF1PayloadError(f"{name} must be a string, got {value!r}")
    return value


def _bool_field(row: JsonObject, name: str) -> bool:
    value = row.get(name)
    if not isinstance(value, bool):
        raise OpenF1PayloadError(f"{name} must be a boolean, got {value!r}")
    return value


def _utc_field(row: JsonObject, name: str) -> datetime:
    raw = _str_field(row, name)
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as error:
        raise OpenF1PayloadError(f"{name} is not an ISO timestamp: {raw!r}") from error
    if value.utcoffset() is None:
        raise OpenF1PayloadError(f"{name} has no timezone: {raw!r}")
    return value
