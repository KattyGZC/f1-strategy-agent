"""Replay pacing: where in its session a replay is at a wall-clock instant (ADR 0009).

Every function here is pure. Session time is seconds since the timeline's first event; wall
time is seconds since the epoch, so every backend process reads the same anchor.
"""

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum

from f1_strategy.domain.replay import Timeline


class ReplaySpeed(IntEnum):
    X1 = 1
    X2 = 2
    X5 = 5
    X10 = 10
    X20 = 20
    X60 = 60


@dataclass(frozen=True)
class Playing:
    """Session time advances at `speed` from `session_s` at the wall instant `wall_s`."""

    speed: ReplaySpeed
    session_s: float
    wall_s: float


@dataclass(frozen=True)
class Paused:
    speed: ReplaySpeed
    session_s: float


type Playback = Playing | Paused


def started(speed: ReplaySpeed, wall_s: float) -> Playing:
    return Playing(speed, 0.0, wall_s)


def session_s_at(playback: Playback, wall_s: float) -> float:
    if isinstance(playback, Paused):
        return playback.session_s
    # Processes read their own clocks; one a little behind the anchor must not rewind.
    elapsed_s = max(0.0, wall_s - playback.wall_s)
    return playback.session_s + elapsed_s * playback.speed


def wall_s_due(playing: Playing, session_s: float) -> float:
    """The wall instant at which a playing replay reaches `session_s`."""
    return playing.wall_s + (session_s - playing.session_s) / playing.speed


def due_until(playback: Playback, offsets: Sequence[float], sent: int, wall_s: float) -> int:
    """The index after the last event due at `wall_s`, counting from the first one not sent.

    A playing replay compares wall instants, the same ones a producer waits for, so an event
    whose wait is over is due whatever the float rounding of session time."""
    if isinstance(playback, Paused):
        return bisect_right(offsets, playback.session_s, lo=sent)
    return bisect_right(
        offsets, wall_s, lo=sent, key=lambda offset_s: wall_s_due(playback, offset_s)
    )


def paused(playback: Playback, wall_s: float) -> Paused:
    return Paused(playback.speed, session_s_at(playback, wall_s))


def resumed(playback: Playback, wall_s: float) -> Playing:
    return Playing(playback.speed, session_s_at(playback, wall_s), wall_s)


def with_speed(playback: Playback, speed: ReplaySpeed, wall_s: float) -> Playback:
    if isinstance(playback, Paused):
        return Paused(speed, playback.session_s)
    return Playing(speed, session_s_at(playback, wall_s), wall_s)


def offsets_s(timeline: Timeline) -> tuple[float, ...]:
    """Each event's session time, in timeline order."""
    if not timeline.events:
        return ()
    first = timeline.events[0].at
    return tuple((event.at - first).total_seconds() for event in timeline.events)
