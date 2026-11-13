from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import LiteralString

import psycopg
import pytest
from psycopg import errors

from f1_strategy.adapters.clean_store import (
    Pool,
    PostgresCalibrationStore,
    PostgresCleanStore,
    connection_pool,
)
from f1_strategy.adapters.migrate import upgrade
from f1_strategy.application.calibration import (
    CalibrateSeason,
    CalibrationFailed,
    CalibrationOutcome,
    CalibrationStatus,
    Fingerprint,
    Race,
    RaceOutcome,
    StoredCalibration,
)
from f1_strategy.application.transform import Load, Version
from f1_strategy.domain.clean import CleanSession, Compound, clean_session, content_hash
from f1_strategy.domain.clean_laps import ExclusionReason
from f1_strategy.domain.lap_time_model import (
    CALIBRATION_VERSION,
    Calibration,
    CompoundFit,
    DriverPace,
    Exclusion,
    NotCalibrated,
    NotCalibratedReason,
    TrackTemperature,
)
from tests.postgres import CONNECT_TIMEOUT_S, fresh_database
from tests.samples import QUALIFYING, RACE, sample

NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)
RACE_KEY = int(RACE)
RACE_SESSION = clean_session(sample(RACE).raw())
FINGERPRINT = Fingerprint(content_hash(RACE_SESSION), CALIBRATION_VERSION)
DRIVERS = tuple(driver.driver_number for driver in RACE_SESSION.drivers)
CALIBRATION = Calibration(
    race_laps=57,
    compounds=(
        CompoundFit(Compound.SOFT, Decimal("97.8"), Decimal("0.129"), Decimal("-0.071"),
                    Decimal("0.48"), 293, 1, 18),
        CompoundFit(Compound.INTERMEDIATE, Decimal("112.7"), Decimal("-0.1"), Decimal("-0.36"),
                    Decimal("1.54"), 186, 0, 30),
    ),
    drivers=(DriverPace(DRIVERS[0], Decimal("0.25"), 40),
             DriverPace(DRIVERS[1], Decimal("-0.25"), 41)),
    residual_rmse_s=Decimal("0.453584"),
    exclusions=(Exclusion(ExclusionReason.FIRST_LAP, 20), Exclusion(ExclusionReason.OUTLIER, 3)),
    track_temperature=TrackTemperature(Decimal("21.9"), Decimal("22.8"), Decimal("23.9")),
)  # fmt: skip
NOT_CALIBRATED = NotCalibrated(
    NotCalibratedReason.NO_CLEAN_LAPS, (Exclusion(ExclusionReason.NO_DURATION, 2),)
)


@pytest.fixture
def postgres_uri(postgres_server_uri: str) -> str:
    uri = fresh_database(postgres_server_uri)
    upgrade(uri, CONNECT_TIMEOUT_S)
    return uri


@pytest.fixture
async def pool(postgres_uri: str) -> AsyncIterator[Pool]:
    pool: Pool = connection_pool(postgres_uri, max_size=2, connect_timeout_s=CONNECT_TIMEOUT_S)
    async with pool:
        yield pool


async def load(pool: Pool, session: CleanSession) -> None:
    async with PostgresCleanStore(pool).claim(
        session.session.session_key, Version("input", "1"), NOW
    ) as claim:
        assert claim is not None
        await claim.replace(Load(session, Version("input", "1"), content_hash(session), NOW))


@pytest.fixture
async def store(pool: Pool) -> PostgresCalibrationStore:
    await load(pool, RACE_SESSION)
    await load(pool, clean_session(sample(QUALIFYING).raw()))
    return PostgresCalibrationStore(pool)


def rows(postgres_uri: str, query: LiteralString) -> list[tuple[object, ...]]:
    with psycopg.connect(postgres_uri, connect_timeout=CONNECT_TIMEOUT_S) as connection:
        return connection.execute(query).fetchall()


@pytest.mark.anyio
async def test_the_races_of_a_season_are_its_loaded_grand_prix(
    store: PostgresCalibrationStore,
) -> None:
    assert await store.races(2024) == (Race(RACE_KEY, FINGERPRINT.clean_output_hash),)
    assert await store.races(2023) == ()


@pytest.mark.anyio
async def test_a_snapshot_holds_the_race_rows_and_their_hash(
    store: PostgresCalibrationStore,
) -> None:
    snapshot = await store.snapshot(RACE_KEY)

    assert snapshot is not None
    assert snapshot.clean_output_hash == FINGERPRINT.clean_output_hash
    assert (
        snapshot.rows.laps, snapshot.rows.stints, snapshot.rows.pits,
        snapshot.rows.race_control, snapshot.rows.weather,
    ) == (
        RACE_SESSION.laps, RACE_SESSION.stints, RACE_SESSION.pits,
        RACE_SESSION.race_control, RACE_SESSION.weather,
    )  # fmt: skip


@pytest.mark.anyio
async def test_a_session_not_loaded_has_no_snapshot(store: PostgresCalibrationStore) -> None:
    assert await store.snapshot(1) is None


@pytest.mark.anyio
async def test_a_saved_calibration_is_stored_whole(
    store: PostgresCalibrationStore, postgres_uri: str
) -> None:
    await store.save(RACE_KEY, FINGERPRINT, CALIBRATION, NOW)

    assert await store.stored([RACE_KEY]) == {
        RACE_KEY: StoredCalibration(CalibrationStatus.CALIBRATED, FINGERPRINT)
    }
    assert rows(postgres_uri, "SELECT race_laps, residual_rmse_s, track_temperature_min_c, "
                "track_temperature_median_c, track_temperature_max_c FROM calibration") == [
        (57, Decimal("0.453584"), Decimal("21.9"), Decimal("22.8"), Decimal("23.9"))
    ]  # fmt: skip
    assert rows(postgres_uri, "SELECT compound::text, base_s, degradation_s_per_lap, "
                "progress_s_per_lap, residual_rmse_s, clean_laps, min_tyre_age_laps, "
                "max_tyre_age_laps FROM calibration_compound c ORDER BY c.compound") == [
        ("SOFT", Decimal("97.8"), Decimal("0.129"), Decimal("-0.071"), Decimal("0.48"), 293, 1, 18),
        ("INTERMEDIATE", Decimal("112.7"), Decimal("-0.1"), Decimal("-0.36"), Decimal("1.54"),
         186, 0, 30),
    ]  # fmt: skip
    assert rows(postgres_uri, "SELECT driver_number, pace_offset_s, clean_laps "
                "FROM calibration_driver ORDER BY driver_number") == [
        (DRIVERS[0], Decimal("0.25"), 40), (DRIVERS[1], Decimal("-0.25"), 41)
    ]  # fmt: skip
    assert rows(postgres_uri, "SELECT reason::text, laps FROM calibration_exclusion "
                "ORDER BY reason") == [("first_lap", 20), ("outlier", 3)]  # fmt: skip


@pytest.mark.anyio
async def test_a_race_without_a_track_temperature_is_stored(
    store: PostgresCalibrationStore, postgres_uri: str
) -> None:
    calibration = Calibration(
        CALIBRATION.race_laps, CALIBRATION.compounds, CALIBRATION.drivers,
        CALIBRATION.residual_rmse_s, CALIBRATION.exclusions, track_temperature=None,
    )  # fmt: skip

    await store.save(RACE_KEY, FINGERPRINT, calibration, NOW)

    nulls = rows(
        postgres_uri,
        "SELECT num_nulls(track_temperature_min_c, track_temperature_median_c, "
        "track_temperature_max_c) FROM calibration",
    )
    assert nulls == [(3,)]


@pytest.mark.anyio
async def test_a_new_result_replaces_the_previous_calibration_whole(
    store: PostgresCalibrationStore, postgres_uri: str
) -> None:
    await store.save(RACE_KEY, FINGERPRINT, CALIBRATION, NOW)
    next_version = Fingerprint(FINGERPRINT.clean_output_hash, "next")

    await store.save(RACE_KEY, next_version, NOT_CALIBRATED, NOW)

    assert await store.stored([RACE_KEY]) == {
        RACE_KEY: StoredCalibration(CalibrationStatus.NOT_CALIBRATED, next_version)
    }
    assert rows(postgres_uri, "SELECT not_calibrated_reason::text, error_message "
                "FROM calibration_run") == [("no_clean_laps", None)]  # fmt: skip
    assert rows(postgres_uri, "SELECT count(*) FROM calibration") == [(0,)]
    assert rows(postgres_uri, "SELECT reason::text, laps FROM calibration_exclusion") == [
        ("no_duration", 2)
    ]


@pytest.mark.anyio
async def test_a_failed_calibration_keeps_its_error_and_no_rows(
    store: PostgresCalibrationStore, postgres_uri: str
) -> None:
    await store.save(RACE_KEY, FINGERPRINT, CALIBRATION, NOW)

    await store.save(RACE_KEY, FINGERPRINT, CalibrationFailed("bad message"), NOW)

    assert await store.stored([RACE_KEY]) == {
        RACE_KEY: StoredCalibration(CalibrationStatus.FAILED, FINGERPRINT)
    }
    assert rows(postgres_uri, "SELECT status::text, error_message FROM calibration_run") == [
        ("failed", "bad message")
    ]
    assert rows(postgres_uri, "SELECT (SELECT count(*) FROM calibration), "
                "(SELECT count(*) FROM calibration_exclusion)") == [(0, 0)]  # fmt: skip


@pytest.mark.anyio
async def test_reloading_the_session_drops_its_calibration(
    store: PostgresCalibrationStore, pool: Pool, postgres_uri: str
) -> None:
    await store.save(RACE_KEY, FINGERPRINT, CALIBRATION, NOW)

    await load(pool, RACE_SESSION)

    assert await store.stored([RACE_KEY]) == {}
    assert rows(postgres_uri, "SELECT (SELECT count(*) FROM calibration_compound), "
                "(SELECT count(*) FROM calibration_driver)") == [(0, 0)]  # fmt: skip


@pytest.mark.anyio
async def test_a_season_is_calibrated_then_found_unchanged(
    store: PostgresCalibrationStore,
) -> None:
    calibrate_season = CalibrateSeason(store)

    first, second = await calibrate_season(2024, NOW), await calibrate_season(2024, NOW)

    reason = NotCalibratedReason.NO_CLEAN_LAPS
    assert first.outcomes == (RaceOutcome(RACE_KEY, CalibrationOutcome.NOT_CALIBRATED, reason),)
    assert second.outcomes == (RaceOutcome(RACE_KEY, CalibrationOutcome.UNCHANGED),)


@pytest.mark.parametrize(
    ("status", "constraint"),
    [
        pytest.param("not_calibrated", "not_calibrated_has_reason", id="no reason"),
        pytest.param("failed", "failed_has_error", id="no error"),
    ],
)
@pytest.mark.anyio
@pytest.mark.usefixtures("store")
async def test_a_run_row_that_contradicts_its_status_is_rejected(
    pool: Pool, status: str, constraint: str
) -> None:
    async with pool.connection() as connection:
        with pytest.raises(errors.CheckViolation) as rejected:
            await connection.execute(
                "INSERT INTO calibration_run (session_key, status, clean_output_hash, "
                "calibration_version, calibrated_at) VALUES (%s, %s, 'h', 'v', now())",
                [RACE_KEY, status],
            )

    assert rejected.value.diag.constraint_name == constraint


@pytest.mark.anyio
async def test_a_wet_compound_cannot_be_calibrated(store: PostgresCalibrationStore) -> None:
    wet = CompoundFit(Compound.WET, Decimal(120), Decimal(0), Decimal(0), Decimal(1), 10, 0, 9)
    calibration = Calibration(
        CALIBRATION.race_laps, (wet,), CALIBRATION.drivers, CALIBRATION.residual_rmse_s,
        CALIBRATION.exclusions, CALIBRATION.track_temperature,
    )  # fmt: skip

    with pytest.raises(errors.CheckViolation) as rejected:
        await store.save(RACE_KEY, FINGERPRINT, calibration, NOW)

    assert rejected.value.diag.constraint_name == "calibration_compound_compound_check"
    assert await store.stored([RACE_KEY]) == {}
