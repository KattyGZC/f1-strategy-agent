"""The replay timeline: one session's clean rows as one ordered list of events (ADR 0009).

Every function here is pure. The same rows give the same events in the same order, so a
replay's content never depends on how fast or when it is played.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from f1_strategy.domain.clean import (
    Compound,
    Interval,
    Lap,
    Overtake,
    Pit,
    Position,
    RaceControl,
    Stint,
    TeamRadio,
    Weather,
)

MICROSECONDS_PER_S = 1_000_000


class EventKind(StrEnum):
    """Event kinds in the order that breaks a tie between events of the same instant."""

    RACE_CONTROL = "race_control"
    WEATHER = "weather"
    PIT = "pit"
    LAP = "lap"
    POSITION = "position"
    INTERVAL = "interval"
    OVERTAKE = "overtake"
    TEAM_RADIO = "team_radio"


KIND_RANK = {kind: rank for rank, kind in enumerate(EventKind)}


@dataclass(frozen=True)
class LapCompleted:
    """A lap at the instant it ended, with the tyre it was driven on. A lap no stint covers has
    no compound and no tyre age: the source does not say."""

    lap: Lap
    compound: Compound | None
    tyre_age_laps: int | None


type EventPayload = (
    RaceControl | Weather | Pit | LapCompleted | Position | Interval | Overtake | TeamRadio
)


@dataclass(frozen=True)
class Event:
    at: datetime
    payload: EventPayload

    @property
    def kind(self) -> EventKind:
        return _KIND_OF_PAYLOAD[type(self.payload)]


@dataclass(frozen=True)
class Timeline:
    """`lap_starts` holds, by lap number, the earliest instant any driver started that lap; a
    lap no driver has a start for is missing."""

    events: tuple[Event, ...]
    laps_without_instant: int
    lap_starts: Mapping[int, datetime]


_KIND_OF_PAYLOAD: dict[type[EventPayload], EventKind] = {
    RaceControl: EventKind.RACE_CONTROL,
    Weather: EventKind.WEATHER,
    Pit: EventKind.PIT,
    LapCompleted: EventKind.LAP,
    Position: EventKind.POSITION,
    Interval: EventKind.INTERVAL,
    Overtake: EventKind.OVERTAKE,
    TeamRadio: EventKind.TEAM_RADIO,
}


class TimelineRows(Protocol):
    """The clean rows a timeline is built from, all of one session."""

    @property
    def laps(self) -> Sequence[Lap]: ...
    @property
    def stints(self) -> Sequence[Stint]: ...
    @property
    def pits(self) -> Sequence[Pit]: ...
    @property
    def intervals(self) -> Sequence[Interval]: ...
    @property
    def positions(self) -> Sequence[Position]: ...
    @property
    def race_control(self) -> Sequence[RaceControl]: ...
    @property
    def weather(self) -> Sequence[Weather]: ...
    @property
    def overtakes(self) -> Sequence[Overtake]: ...
    @property
    def team_radio(self) -> Sequence[TeamRadio]: ...


def timeline(rows: TimelineRows) -> Timeline:
    laps = _laps_completed(rows.laps, rows.stints)
    events = [
        *laps,
        *(Event(row.date, row) for row in rows.race_control),
        *(Event(row.date, row) for row in rows.weather),
        *(Event(row.date, row) for row in rows.pits),
        *(Event(row.date, row) for row in rows.positions),
        *(Event(row.date, row) for row in rows.intervals),
        *(Event(row.date, row) for row in rows.overtakes),
        *(Event(row.date, row) for row in rows.team_radio),
    ]
    return Timeline(
        tuple(sorted(events, key=_order)), len(rows.laps) - len(laps), _lap_starts(rows.laps)
    )


def _lap_starts(laps: Sequence[Lap]) -> dict[int, datetime]:
    # Every lap with a start counts, completed or not: lap 1 often has a start but no
    # duration (547 in the 2024 season, psql 2026-11-10).
    starts: dict[int, datetime] = {}
    for lap in laps:
        if lap.date_start is not None:
            earliest = starts.get(lap.lap_number, lap.date_start)
            starts[lap.lap_number] = min(earliest, lap.date_start)
    return starts


def _laps_completed(laps: Sequence[Lap], stints: Sequence[Stint]) -> list[Event]:
    # Newest stint first: consecutive stints share their boundary lap (ADR 0008), and the lap
    # belongs to the stint that starts on it.
    newest_first: defaultdict[int, list[Stint]] = defaultdict(list)
    for stint in sorted(stints, key=lambda stint: stint.stint_number, reverse=True):
        newest_first[stint.driver_number].append(stint)
    events = []
    for lap in laps:
        if lap.date_start is None or lap.lap_duration is None:
            continue
        ended_at = lap.date_start + _duration(lap.lap_duration)
        events.append(Event(ended_at, _with_tyre(lap, newest_first[lap.driver_number])))
    return events


def _duration(seconds: Decimal) -> timedelta:
    # Instants carry microseconds (timestamptz), so a duration is cut to that; 2024 durations
    # have at most three decimals, so none loses anything.
    return timedelta(microseconds=int(seconds * MICROSECONDS_PER_S))


def _with_tyre(lap: Lap, newest_first: Sequence[Stint]) -> LapCompleted:
    for stint in newest_first:
        if stint.lap_start is None or stint.lap_end is None:
            continue
        if stint.lap_start <= lap.lap_number <= stint.lap_end:
            tyre_age_laps = stint.tyre_age_at_start + lap.lap_number - stint.lap_start
            return LapCompleted(lap, stint.compound, tyre_age_laps)
    return LapCompleted(lap, None, None)


def _order(event: Event) -> tuple[datetime, int, tuple[int, ...]]:
    return event.at, KIND_RANK[event.kind], _row_key(event.payload)


def _row_key(payload: EventPayload) -> tuple[int, ...]:
    match payload:
        case RaceControl():
            return (payload.seq,)
        case Weather():
            return ()
        case LapCompleted():
            return payload.lap.driver_number, payload.lap.lap_number
        case Overtake():
            return payload.overtaking_driver_number, payload.overtaken_driver_number
        case _:
            return (payload.driver_number,)
