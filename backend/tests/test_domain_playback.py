from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from f1_strategy.domain.clean import Lap, Position
from f1_strategy.domain.playback import (
    Paused,
    Playback,
    Playing,
    ReplaySpeed,
    due_until,
    lap_start_s,
    offsets_s,
    paused,
    resumed,
    session_s_at,
    sought,
    started,
    wall_s_due,
    with_speed,
)
from f1_strategy.domain.replay import Timeline, timeline
from tests.replay_rows import Rows

T0 = datetime(2024, 3, 2, 15, tzinfo=UTC)
WALL_S = 1_000.0


def lap_started(lap_number: int, date_start: datetime) -> Lap:
    return Lap(
        1, 1, lap_number, date_start, None, None, None, None, None, None, None,
        is_pit_out_lap=False,
    )  # fmt: skip


def test_a_started_replay_is_at_the_first_event() -> None:
    assert started(ReplaySpeed.X10, WALL_S) == Playing(ReplaySpeed.X10, 0.0, WALL_S)


@pytest.mark.parametrize("speed", list(ReplaySpeed))
def test_session_time_advances_at_the_speed(speed: ReplaySpeed) -> None:
    playing = Playing(speed, 30.0, WALL_S)

    assert session_s_at(playing, WALL_S + 2.0) == 30.0 + 2.0 * speed


def test_session_time_does_not_rewind_on_a_clock_behind_the_anchor() -> None:
    playing = Playing(ReplaySpeed.X5, 30.0, WALL_S)

    assert session_s_at(playing, WALL_S - 1.0) == 30.0


def test_session_time_stands_still_while_paused() -> None:
    assert session_s_at(Paused(ReplaySpeed.X5, 42.0), WALL_S + 600.0) == 42.0


def test_an_event_falls_due_when_session_time_reaches_it() -> None:
    playing = Playing(ReplaySpeed.X20, 100.0, WALL_S)

    due_s = wall_s_due(playing, 160.0)

    assert due_s == WALL_S + 3.0
    assert session_s_at(playing, due_s) == 160.0


@pytest.mark.parametrize(
    "playback",
    [Paused(ReplaySpeed.X1, 0.0), Playing(ReplaySpeed.X1, 0.0, WALL_S)],
    ids=["paused", "playing"],
)
def test_events_already_sent_stay_sent(playback: Paused | Playing) -> None:
    offsets = [0.0, 1.0, 2.0, 3.0]

    assert due_until(playback, offsets, 3, WALL_S) == 3


def test_pausing_keeps_the_session_time() -> None:
    playing = Playing(ReplaySpeed.X2, 10.0, WALL_S)

    assert paused(playing, WALL_S + 5.0) == Paused(ReplaySpeed.X2, 20.0)


def test_pausing_twice_changes_nothing() -> None:
    once = Paused(ReplaySpeed.X2, 20.0)

    assert paused(once, WALL_S + 99.0) == once


def test_resuming_starts_from_the_paused_session_time() -> None:
    assert resumed(Paused(ReplaySpeed.X5, 20.0), WALL_S) == Playing(ReplaySpeed.X5, 20.0, WALL_S)


def test_resuming_a_playing_replay_keeps_its_session_time() -> None:
    playing = Playing(ReplaySpeed.X5, 20.0, WALL_S)

    assert resumed(playing, WALL_S + 2.0) == Playing(ReplaySpeed.X5, 30.0, WALL_S + 2.0)


def test_a_new_speed_applies_from_the_current_session_time() -> None:
    playing = Playing(ReplaySpeed.X1, 10.0, WALL_S)

    faster = with_speed(playing, ReplaySpeed.X60, WALL_S + 4.0)

    assert faster == Playing(ReplaySpeed.X60, 14.0, WALL_S + 4.0)
    assert session_s_at(faster, WALL_S + 5.0) == 74.0


def test_a_new_speed_while_paused_stays_paused() -> None:
    result = with_speed(Paused(ReplaySpeed.X1, 14.0), ReplaySpeed.X10, WALL_S)

    assert result == Paused(ReplaySpeed.X10, 14.0)


def test_offsets_count_from_the_first_event() -> None:
    rows = Rows(
        positions=[
            Position(1, 1, T0, 1),
            Position(1, 16, T0 + timedelta(seconds=1.5), 2),
            Position(1, 1, T0 + timedelta(minutes=2), 1),
        ]
    )

    assert offsets_s(timeline(rows)) == (0.0, 1.5, 120.0)


def test_an_empty_timeline_has_no_offsets() -> None:
    assert offsets_s(Timeline((), 0, {})) == ()


def test_seeking_a_playing_replay_plays_on_from_there() -> None:
    playing = Playing(ReplaySpeed.X10, 500.0, WALL_S)

    assert sought(playing, 120.0, WALL_S + 7.0) == Playing(ReplaySpeed.X10, 120.0, WALL_S + 7.0)


def test_seeking_a_paused_replay_stays_paused_there() -> None:
    assert sought(Paused(ReplaySpeed.X5, 500.0), 120.0, WALL_S) == Paused(ReplaySpeed.X5, 120.0)


# Instants carry microseconds (timestamptz), so session times are whole microseconds.
SESSION_TIMES_S = st.integers(0, 10_000 * 1_000_000).map(lambda microseconds: microseconds / 1e6)


@given(
    offsets=st.lists(SESSION_TIMES_S, max_size=50).map(sorted),
    session_s=SESSION_TIMES_S,
    before=st.sampled_from(
        [Playing(speed, 0.0, 0.0) for speed in ReplaySpeed]
        + [Paused(speed, 0.0) for speed in ReplaySpeed]
    ),
)
def test_after_a_seek_exactly_the_events_up_to_it_are_due(
    offsets: list[float], session_s: float, before: Playback
) -> None:
    seek = sought(before, session_s, WALL_S)

    assert due_until(seek, offsets, 0, WALL_S) == sum(offset <= session_s for offset in offsets)


def test_a_lap_starts_where_its_earliest_driver_started_it() -> None:
    rows = Rows(
        positions=[Position(1, 1, T0, 1)],
        laps=[lap_started(3, T0 + timedelta(seconds=95.5))],
    )

    assert lap_start_s(timeline(rows), 3) == 95.5


def test_a_lap_before_the_first_event_starts_before_the_session_time_zero() -> None:
    rows = Rows(
        positions=[Position(1, 1, T0, 1)],
        laps=[lap_started(1, T0 - timedelta(seconds=10))],
    )

    assert lap_start_s(timeline(rows), 1) == -10.0


def test_a_lap_without_a_start_cannot_be_sought() -> None:
    rows = Rows(positions=[Position(1, 1, T0, 1)])

    assert lap_start_s(timeline(rows), 3) is None


def test_a_timeline_without_events_has_no_lap_to_seek() -> None:
    assert lap_start_s(Timeline((), 0, {1: T0}), 1) is None
