from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from f1_strategy.application.calibration import (
    UNCHANGED_FAILURE,
    CalibrateSeason,
    CalibrationFailed,
    CalibrationOutcome,
    CalibrationReport,
    CalibrationResult,
    CalibrationStatus,
    Fingerprint,
    Race,
    RaceOutcome,
    RaceSnapshot,
    SeasonNotTransformedError,
    StoredCalibration,
)
from f1_strategy.domain.lap_time_model import (
    CALIBRATION_VERSION,
    Calibration,
    NotCalibrated,
    NotCalibratedReason,
    calibrate,
)
from tests.replay_rows import Rows
from tests.synthetic_race import T0, race_control, synthetic_race

NOW = datetime(2026, 11, 12, tzinfo=UTC)
RACE_KEY, OTHER_KEY = 9472, 9480


@dataclass
class FakeStore:
    """The clean model holding the season's races, and the calibrations saved so far."""

    snapshots: dict[int, RaceSnapshot | None]
    saved: dict[int, tuple[Fingerprint, CalibrationResult]] = field(default_factory=dict)
    listed_hashes: dict[int, str] = field(default_factory=dict)

    async def races(self, year: int) -> tuple[Race, ...]:
        assert year == 2024
        return tuple(
            Race(key, self.listed_hashes.get(key, _hash(key))) for key in sorted(self.snapshots)
        )

    async def stored(self, session_keys: Collection[int]) -> dict[int, StoredCalibration]:
        return {
            key: StoredCalibration(_status(result), fingerprint)
            for key, (fingerprint, result) in self.saved.items()
            if key in session_keys
        }

    async def snapshot(self, session_key: int) -> RaceSnapshot | None:
        return self.snapshots[session_key]

    async def save(
        self, session_key: int, fingerprint: Fingerprint, result: CalibrationResult, now: datetime
    ) -> None:
        assert now == NOW
        self.saved[session_key] = (fingerprint, result)


def _hash(session_key: int) -> str:
    return f"clean-{session_key}"


def _status(result: CalibrationResult) -> CalibrationStatus:
    match result:
        case Calibration():
            return CalibrationStatus.CALIBRATED
        case NotCalibrated():
            return CalibrationStatus.NOT_CALIBRATED
        case CalibrationFailed():
            return CalibrationStatus.FAILED


def snapshot(rows: Rows, session_key: int = RACE_KEY) -> RaceSnapshot:
    return RaceSnapshot(rows, _hash(session_key))


def broken_race() -> Rows:
    rows = synthetic_race()
    rows.race_control = [race_control(4, T0, "SAFETY CAR STAYING OUT")]
    return rows


async def run(store: FakeStore) -> CalibrationReport:
    return await CalibrateSeason(store)(2024, NOW)


@pytest.mark.anyio
async def test_each_race_is_calibrated_and_saved_with_its_fingerprint() -> None:
    store = FakeStore(
        {RACE_KEY: snapshot(synthetic_race()), OTHER_KEY: snapshot(Rows(), OTHER_KEY)}
    )

    report = await run(store)

    no_clean_laps = NotCalibratedReason.NO_CLEAN_LAPS
    assert report == CalibrationReport((
        RaceOutcome(RACE_KEY, CalibrationOutcome.CALIBRATED),
        RaceOutcome(OTHER_KEY, CalibrationOutcome.NOT_CALIBRATED, no_clean_laps),
    ))  # fmt: skip
    assert store.saved == {
        RACE_KEY: (Fingerprint(_hash(RACE_KEY), CALIBRATION_VERSION), calibrate(synthetic_race())),
        OTHER_KEY: (
            Fingerprint(_hash(OTHER_KEY), CALIBRATION_VERSION),
            NotCalibrated(NotCalibratedReason.NO_CLEAN_LAPS, ()),
        ),
    }


@pytest.mark.anyio
async def test_a_second_run_finds_every_race_unchanged() -> None:
    store = FakeStore({RACE_KEY: snapshot(synthetic_race())})
    await run(store)
    saved = dict(store.saved)

    report = await run(store)

    assert report.outcomes == (RaceOutcome(RACE_KEY, CalibrationOutcome.UNCHANGED),)
    assert store.saved == saved


@pytest.mark.anyio
async def test_a_race_whose_clean_rows_changed_is_calibrated_again() -> None:
    store = FakeStore({RACE_KEY: snapshot(synthetic_race())})
    store.saved[RACE_KEY] = (
        Fingerprint("clean-before", CALIBRATION_VERSION),
        CalibrationFailed("x"),
    )

    report = await run(store)

    assert report.outcomes == (RaceOutcome(RACE_KEY, CalibrationOutcome.CALIBRATED),)


@pytest.mark.anyio
async def test_a_new_calibration_version_calibrates_every_race_again() -> None:
    store = FakeStore({RACE_KEY: snapshot(synthetic_race())})
    store.saved[RACE_KEY] = (
        Fingerprint(_hash(RACE_KEY), "0"),
        NotCalibrated(NotCalibratedReason.NO_CLEAN_LAPS, ()),
    )

    report = await run(store)

    assert report.outcomes == (RaceOutcome(RACE_KEY, CalibrationOutcome.CALIBRATED),)
    assert store.saved[RACE_KEY][0] == Fingerprint(_hash(RACE_KEY), CALIBRATION_VERSION)


@pytest.mark.anyio
async def test_race_data_the_model_does_not_describe_fails_that_race_alone() -> None:
    store = FakeStore(
        {RACE_KEY: snapshot(broken_race()), OTHER_KEY: snapshot(synthetic_race(), OTHER_KEY)}
    )

    report = await run(store)

    message = "race_control seq 4: safety car message 'SAFETY CAR STAYING OUT'"
    assert report.outcomes == (
        RaceOutcome(RACE_KEY, CalibrationOutcome.FAILED, message),
        RaceOutcome(OTHER_KEY, CalibrationOutcome.CALIBRATED),
    )
    assert report.failures == (report.outcomes[0],)
    assert store.saved[RACE_KEY][1] == CalibrationFailed(message)


@pytest.mark.anyio
async def test_a_failed_race_whose_rows_did_not_change_is_still_failing() -> None:
    store = FakeStore({RACE_KEY: snapshot(broken_race())})
    await run(store)

    report = await run(store)

    still = RaceOutcome(RACE_KEY, CalibrationOutcome.STILL_FAILING, UNCHANGED_FAILURE)
    assert (report.outcomes, report.failures) == ((still,), (still,))


@pytest.mark.anyio
async def test_the_fingerprint_is_the_one_of_the_rows_read() -> None:
    store = FakeStore({RACE_KEY: snapshot(synthetic_race())}, listed_hashes={RACE_KEY: "listed"})

    await run(store)

    assert store.saved[RACE_KEY][0] == Fingerprint(_hash(RACE_KEY), CALIBRATION_VERSION)


@pytest.mark.anyio
async def test_a_race_removed_while_the_season_is_calibrated_is_gone() -> None:
    store = FakeStore({RACE_KEY: None})

    report = await run(store)

    assert report.outcomes == (RaceOutcome(RACE_KEY, CalibrationOutcome.GONE),)
    assert store.saved == {}


@pytest.mark.anyio
async def test_a_season_with_no_race_in_the_clean_model_fails() -> None:
    with pytest.raises(SeasonNotTransformedError, match="no race of 2024 is in the clean model"):
        await run(FakeStore({}))


def test_the_report_counts_each_outcome() -> None:
    report = CalibrationReport((
        RaceOutcome(1, CalibrationOutcome.CALIBRATED),
        RaceOutcome(2, CalibrationOutcome.CALIBRATED),
        RaceOutcome(3, CalibrationOutcome.UNCHANGED),
    ))  # fmt: skip

    assert [report.count(outcome) for outcome in CalibrationOutcome] == [2, 0, 1, 0, 0, 0]
