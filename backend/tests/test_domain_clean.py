import copy
import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import pytest

from f1_strategy.domain.clean import (
    TRANSFORM_VERSION,
    CleanDataError,
    Compound,
    Lap,
    RawSession,
    clean_session,
    column_names,
    content_hash,
    input_fingerprint,
)
from f1_strategy.domain.openf1 import Endpoint, JsonObject, JsonValue, SessionName, SessionType

SAMPLE = Path(__file__).parent / "fixtures" / "openf1_2024_bahrain_sample.json"
RACE = "9472"
QUALIFYING = "9468"

# One entry per TRANSFORM_VERSION: the content hash of the sample's two sessions. A change to the
# clean rows turns this test red; the fix is a new version with its new hash, never a new hash
# under an old version.
GOLDEN = {
    "1": (
        "bc0e46463d1779eb19a671442ef83db48d8367d7402d2381a8b7d7c089bdcc1c",
        "55d061f834f95c2a203c6a960084b020d8d7f380071dcf51f68d2d219ee8b3d1",
    ),
}


@dataclass
class Sample:
    """A mutable copy of one sampled session, to break before cleaning it."""

    session: JsonObject
    meeting: JsonObject
    rows: dict[Endpoint, list[JsonObject]]

    def raw(self) -> RawSession:
        return RawSession(self.session, self.meeting, self.rows)

    def driver_rows(self, endpoint: Endpoint, driver_number: int) -> list[JsonObject]:
        return [row for row in self.rows[endpoint] if row["driver_number"] == driver_number]


def sample(session_key: str) -> Sample:
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))[session_key]
    rows = {Endpoint(endpoint): endpoint_rows for endpoint, endpoint_rows in data["rows"].items()}
    return Sample(data["session"], data["meeting"], rows)


def with_row(
    sample_key: str, endpoint: Endpoint, index: int, /, **changes: JsonValue
) -> RawSession:
    data = sample(sample_key)
    data.rows[endpoint][index].update(changes)
    return data.raw()


def integer(value: JsonValue) -> int:
    assert isinstance(value, int)
    return value


def rejected(raw: RawSession) -> str:
    with pytest.raises(CleanDataError) as error:
        clean_session(raw)
    return str(error.value)


def test_the_golden_sample_pins_the_transform_version() -> None:
    hashes = tuple(content_hash(clean_session(sample(key).raw())) for key in (RACE, QUALIFYING))

    assert hashes == GOLDEN[TRANSFORM_VERSION]


@pytest.mark.parametrize("seed", range(5))
def test_the_order_of_raw_rows_does_not_change_the_clean_rows(seed: int) -> None:
    data = sample(RACE)
    shuffler = random.Random(seed)  # noqa: S311 - a test shuffle, not a secret
    for endpoint, rows in data.rows.items():
        if endpoint != Endpoint.RACE_CONTROL:  # its order is its key
            shuffler.shuffle(rows)

    shuffled = content_hash(clean_session(data.raw()))

    assert shuffled == GOLDEN[TRANSFORM_VERSION][0]


@pytest.mark.parametrize("key", [RACE, QUALIFYING])
def test_every_raw_row_becomes_one_clean_row(key: str) -> None:
    data = sample(key)

    clean = clean_session(data.raw())

    tables = dict(clean.tables())
    raw_counts = {str(endpoint): len(rows) for endpoint, rows in data.rows.items()}
    clean_counts = {
        "drivers": len(tables["driver_session"]),
        "laps": len(tables["lap"]),
        "stints": len(tables["stint"]),
        "pit": len(tables["pit"]),
        "intervals": len(tables["interval"]),
        "position": len(tables["position"]),
        "race_control": len(tables["race_control"]),
        "weather": len(tables["weather"]),
        "session_result": len(tables["session_result"]),
        "starting_grid": len(tables["starting_grid"]),
        "overtakes": len(tables["overtake"]),
        "team_radio": len(tables["team_radio"]),
    }
    assert {endpoint: clean_counts[endpoint] for endpoint in raw_counts} == raw_counts


def test_the_session_and_its_meeting_are_typed() -> None:
    clean = clean_session(sample(RACE).raw())

    assert clean.session.session_type == SessionType.RACE
    assert clean.session.session_name == SessionName.GRAND_PRIX
    assert clean.session.meeting_key == clean.meeting.meeting_key
    assert clean.meeting.gmt_offset == timedelta(hours=3)
    assert clean.meeting.date_start.tzinfo == UTC


def test_numbers_keep_the_digits_openf1_sent() -> None:
    raw = with_row(RACE, Endpoint.LAPS, 0, lap_duration=91.234, i1_speed=None)

    lap = next(lap for lap in clean_session(raw).laps if lap.lap_duration == Decimal("91.234"))

    assert str(lap.lap_duration) == "91.234"
    assert lap.i1_speed is None


def test_timestamps_become_utc() -> None:
    raw = with_row(RACE, Endpoint.WEATHER, 0, date="2024-03-02T17:00:00+02:00")

    dates = [weather.date for weather in clean_session(raw).weather]

    assert datetime(2024, 3, 2, 15, tzinfo=UTC) in dates
    assert all(date.utcoffset() == timedelta(0) for date in dates)


@pytest.mark.parametrize(
    ("gap", "expected"),
    [
        pytest.param(12.5, (Decimal("12.5"), None), id="seconds"),
        pytest.param(0, (Decimal(0), None), id="the leader"),
        pytest.param("+1 LAP", (None, 1), id="one lap"),
        pytest.param("+2 LAPS", (None, 2), id="laps"),
        pytest.param(None, (None, None), id="unknown"),
    ],
)
def test_a_gap_is_seconds_or_laps(
    gap: JsonValue, expected: tuple[Decimal | None, int | None]
) -> None:
    data = sample(RACE)
    data.rows[Endpoint.INTERVALS] = [
        {**data.rows[Endpoint.INTERVALS][0], "gap_to_leader": gap, "interval": gap}
    ]

    interval = clean_session(data.raw()).intervals[0]

    assert (interval.gap_to_leader_s, interval.gap_to_leader_laps) == expected
    assert (interval.interval_s, interval.interval_laps) == expected


def test_race_results_keep_points_and_qualifying_results_split_into_phases() -> None:
    race = clean_session(sample(RACE).raw())
    qualifying = clean_session(sample(QUALIFYING).raw())

    assert all(result.points is not None for result in race.results)
    assert race.qualifying_phases == ()
    assert all(result.points is None and result.duration is None for result in qualifying.results)
    assert [phase.phase for phase in qualifying.qualifying_phases] == [1, 2, 3] * 4


def test_race_control_is_keyed_by_its_position_in_the_raw_document() -> None:
    clean = clean_session(sample(RACE).raw())

    assert [message.seq for message in clean.race_control] == list(range(12))


def test_stints_may_share_the_lap_of_the_stop() -> None:
    data = sample(QUALIFYING)
    stints = data.driver_rows(Endpoint.STINTS, 1)

    clean = clean_session(data.raw())

    assert len([stint for stint in clean.stints if stint.driver_number == 1]) == len(stints)
    assert any(later["lap_start"] == earlier["lap_end"] for earlier, later in pairwise(stints))


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        pytest.param(
            with_row(RACE, Endpoint.STINTS, 0, compound="HYPERSOFT"),
            "stints row 0: compound 'HYPERSOFT' is not one of",
            id="a value outside a closed set",
        ),
        pytest.param(
            with_row(RACE, Endpoint.LAPS, 3, session_key=9999),
            "laps row 3: session_key 9999 is not 9472",
            id="a row of another session",
        ),
        pytest.param(
            with_row(RACE, Endpoint.LAPS, 0, lap_number="1"),
            "laps row 0: lap_number must be an integer",
            id="a number sent as text",
        ),
        pytest.param(
            with_row(RACE, Endpoint.LAPS, 0, is_pit_out_lap=1),
            "laps row 0: is_pit_out_lap must be a boolean",
            id="a boolean sent as a number",
        ),
        pytest.param(
            with_row(RACE, Endpoint.LAPS, 0, lap_duration=True),
            "laps row 0: lap_duration must be a number",
            id="a duration sent as a boolean",
        ),
        pytest.param(
            with_row(RACE, Endpoint.POSITION, 0, date="2024-03-02T15:00:00"),
            "position row 0: date has no timezone",
            id="a naive timestamp",
        ),
        pytest.param(
            with_row(RACE, Endpoint.POSITION, 0, date="yesterday"),
            "position row 0: date is not an ISO timestamp",
            id="not a timestamp",
        ),
        pytest.param(
            with_row(RACE, Endpoint.POSITION, 0, date=None),
            "position row 0: date is null",
            id="a required value missing",
        ),
        pytest.param(
            with_row(RACE, Endpoint.INTERVALS, 0, interval="+1 LAP AHEAD"),
            "intervals row 0: interval '+1 LAP AHEAD' is neither seconds nor laps behind",
            id="a gap in an unknown unit",
        ),
        pytest.param(
            with_row(RACE, Endpoint.PIT, 0, pit_duration=99.9),
            "pit row 0: pit_duration differs from lane_duration",
            id="a pit duration that would be dropped",
        ),
        pytest.param(
            with_row(RACE, Endpoint.WEATHER, 0, rainfall=2),
            "weather row 0: rainfall must be 0 or 1",
            id="rainfall that is not a flag",
        ),
        pytest.param(
            with_row(RACE, Endpoint.SESSION_RESULT, 0, points=None),
            "session_result row 0: points is null",
            id="a race result without points",
        ),
        pytest.param(
            with_row(QUALIFYING, Endpoint.SESSION_RESULT, 0, points=0),
            "session_result row 0: a qualifying result has points",
            id="a qualifying result with points",
        ),
        pytest.param(
            with_row(QUALIFYING, Endpoint.SESSION_RESULT, 0, duration=[90.1, 89.9]),
            "session_result row 0: duration of a qualifying result must be a list of three",
            id="two qualifying phases",
        ),
        pytest.param(
            with_row(RACE, Endpoint.TEAM_RADIO, 0, recording_url=5),
            "team_radio row 0: recording_url must be a string",
            id="a text sent as a number",
        ),
        pytest.param(
            with_row(RACE, Endpoint.TEAM_RADIO, 0, recording_url=None),
            "team_radio row 0: recording_url is null",
            id="a radio without a recording",
        ),
    ],
)
def test_a_row_the_model_does_not_describe_fails_the_session(raw: RawSession, message: str) -> None:
    assert rejected(raw).startswith(message)


def test_a_missing_field_fails_the_session() -> None:
    data = sample(RACE)
    del data.rows[Endpoint.LAPS][0]["st_speed"]

    assert rejected(data.raw()) == "laps row 0: st_speed is missing"


def test_two_rows_with_one_key_fail_the_session() -> None:
    data = sample(RACE)
    laps = data.rows[Endpoint.LAPS]
    laps.append(copy.deepcopy(laps[0]))

    assert rejected(data.raw()).startswith("laps: two rows share the key")


def test_stints_numbered_with_a_gap_fail_the_session() -> None:
    data = sample(RACE)
    stints = data.driver_rows(Endpoint.STINTS, 1)
    stints[-1]["stint_number"] = 9

    assert rejected(data.raw()).startswith("stints: driver 1 has stints numbered")


def test_a_stint_that_skips_laps_fails_the_session() -> None:
    data = sample(RACE)
    stints = data.driver_rows(Endpoint.STINTS, 1)
    stints[1]["lap_start"] = integer(stints[0]["lap_end"]) + 2
    stints[1]["lap_end"] = integer(stints[1]["lap_start"]) + 20

    assert rejected(data.raw()).startswith("stints: driver 1 stint 2 starts on lap")


def test_stints_without_a_lap_range_are_not_compared() -> None:
    data = sample(RACE)
    stints = data.driver_rows(Endpoint.STINTS, 1)
    stints[0].update(lap_start=None, lap_end=None)

    clean_session(data.raw())


def test_a_cancelled_session_fails() -> None:
    data = sample(RACE)
    data.session["is_cancelled"] = True

    assert rejected(data.raw()) == "sessions: the session is cancelled"


def test_a_session_of_another_meeting_fails() -> None:
    data = sample(RACE)
    data.session["meeting_key"] = 1

    assert rejected(data.raw()).startswith("sessions: meeting_key 1 is not the meeting's")


def test_rows_of_an_endpoint_the_session_type_does_not_have_fail() -> None:
    data = sample(QUALIFYING)
    data.rows[Endpoint.INTERVALS] = sample(RACE).rows[Endpoint.INTERVALS]

    assert rejected(data.raw()) == "intervals: not an endpoint of a Qualifying"


@pytest.mark.parametrize(
    ("offset", "expected"),
    [("-05:00:00", -timedelta(hours=5)), ("05:30:00", timedelta(hours=5, minutes=30))],
)
def test_the_meeting_offset_keeps_its_sign(offset: str, expected: timedelta) -> None:
    data = sample(RACE)
    data.meeting["gmt_offset"] = offset

    assert clean_session(data.raw()).meeting.gmt_offset == expected


def test_a_meeting_offset_in_another_format_fails() -> None:
    data = sample(RACE)
    data.meeting["gmt_offset"] = "+3"

    assert rejected(data.raw()) == "meetings: gmt_offset '+3' is not [-]HH:MM:SS"


def test_the_input_fingerprint_depends_on_the_documents_not_their_order() -> None:
    fetched = datetime(2026, 10, 27, 12, tzinfo=UTC)
    documents = [("laps?session_key=9472", fetched), ("pit?session_key=9472", fetched)]

    assert input_fingerprint(documents) == input_fingerprint(reversed(documents))
    assert input_fingerprint(documents) == input_fingerprint(
        [(key, at.astimezone(timezone(timedelta(hours=2)))) for key, at in documents]
    )
    assert input_fingerprint(documents) != input_fingerprint(
        [documents[0], (documents[1][0], fetched + timedelta(seconds=1))]
    )


def test_column_names_are_the_field_names_in_order() -> None:
    assert column_names(Lap)[:3] == ("session_key", "driver_number", "lap_number")
    assert Compound("SOFT") is Compound.SOFT
