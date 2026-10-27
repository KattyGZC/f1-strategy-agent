from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pymongo import AsyncMongoClient

from f1_strategy.adapters.raw_store import (
    COLLECTION,
    ENDPOINT_SESSION_INDEX,
    MongoDocument,
    MongoRawStore,
)
from f1_strategy.domain.openf1 import (
    Endpoint,
    JsonObject,
    Param,
    RawRequest,
    RawResponse,
    meetings_request,
)

FETCHED_AT = datetime(2026, 10, 26, 12, tzinfo=UTC)
LAPS = RawRequest.of(Endpoint.LAPS, {Param.SESSION_KEY: 9472})
MEETINGS = meetings_request(2024, datetime(2025, 1, 1, tzinfo=UTC))
ROWS: list[JsonObject] = [
    {"lap_number": 1, "lap_duration": 100.537, "segments_sector_1": [None, 2048]}
]


@pytest.fixture
async def mongo(mongo_uri: str) -> AsyncIterator[AsyncMongoClient[MongoDocument]]:
    client: AsyncMongoClient[MongoDocument] = AsyncMongoClient(mongo_uri, tz_aware=True)
    async with client:
        yield client


@pytest.fixture
def database() -> str:
    return f"raw_{uuid4().hex}"


@pytest.mark.anyio
async def test_a_stored_response_is_found_with_its_rows(
    mongo: AsyncMongoClient[MongoDocument], database: str
) -> None:
    store = MongoRawStore(mongo, database)

    await store.put(RawResponse(LAPS, ROWS, FETCHED_AT))

    assert await store.contains(LAPS)
    assert await store.rows(LAPS) == ROWS


@pytest.mark.anyio
async def test_the_document_is_keyed_by_the_request_and_keeps_its_provenance(
    mongo: AsyncMongoClient[MongoDocument], database: str
) -> None:
    await MongoRawStore(mongo, database).put(RawResponse(LAPS, ROWS, FETCHED_AT))

    document = await mongo[database][COLLECTION].find_one({"_id": LAPS.key})

    assert document == {
        "_id": "laps?session_key=9472",
        "endpoint": "laps",
        "params": {"session_key": 9472},
        "session_key": 9472,
        "rows": ROWS,
        "fetched_at": FETCHED_AT,
    }


@pytest.mark.anyio
async def test_a_request_without_a_session_is_stored_with_a_null_session_key(
    mongo: AsyncMongoClient[MongoDocument], database: str
) -> None:
    await MongoRawStore(mongo, database).put(RawResponse(MEETINGS, [], FETCHED_AT))

    document = await mongo[database][COLLECTION].find_one({"_id": MEETINGS.key})

    assert document is not None
    assert document["session_key"] is None
    assert document["rows"] == []


@pytest.mark.anyio
async def test_an_unknown_request_is_absent(
    mongo: AsyncMongoClient[MongoDocument], database: str
) -> None:
    store = MongoRawStore(mongo, database)

    assert not await store.contains(LAPS)
    assert await store.rows(LAPS) is None


@pytest.mark.anyio
async def test_an_empty_response_is_stored_and_distinct_from_absent(
    mongo: AsyncMongoClient[MongoDocument], database: str
) -> None:
    store = MongoRawStore(mongo, database)

    await store.put(RawResponse(LAPS, [], FETCHED_AT))

    assert await store.contains(LAPS)
    assert await store.rows(LAPS) == []


@pytest.mark.anyio
async def test_a_second_write_of_the_same_request_is_ignored_and_never_overwrites(
    mongo: AsyncMongoClient[MongoDocument], database: str
) -> None:
    store = MongoRawStore(mongo, database)
    await store.put(RawResponse(LAPS, ROWS, FETCHED_AT))

    await store.put(RawResponse(LAPS, [{"lap_number": 99}], datetime(2027, 1, 1, tzinfo=UTC)))

    assert await store.rows(LAPS) == ROWS
    assert await mongo[database][COLLECTION].count_documents({}) == 1


@pytest.mark.anyio
async def test_stored_rows_that_are_not_objects_fail_loud(
    mongo: AsyncMongoClient[MongoDocument], database: str
) -> None:
    await mongo[database][COLLECTION].insert_one({"_id": LAPS.key, "rows": ["lap"]})

    with pytest.raises(TypeError, match=r"stored rows of laps\?session_key=9472"):
        await MongoRawStore(mongo, database).rows(LAPS)


def telemetry(endpoint: Endpoint, session_key: int) -> RawRequest:
    return RawRequest.of(endpoint, {Param.SESSION_KEY: session_key, Param.DRIVER_NUMBER: 1})


@pytest.mark.anyio
async def test_deleting_telemetry_keeps_the_given_session_and_every_other_endpoint(
    mongo: AsyncMongoClient[MongoDocument], database: str
) -> None:
    store = MongoRawStore(mongo, database)
    kept = [
        telemetry(Endpoint.CAR_DATA, 11396),
        telemetry(Endpoint.LOCATION, 11396),
        LAPS,
        MEETINGS,
    ]
    deleted = [telemetry(Endpoint.CAR_DATA, 9472), telemetry(Endpoint.LOCATION, 9472)]
    for request in kept + deleted:
        await store.put(RawResponse(request, [], FETCHED_AT))

    deleted_count = await store.delete_telemetry_except(11396)

    assert deleted_count == len(deleted)
    remaining = await mongo[database][COLLECTION].distinct("_id")
    assert sorted(remaining) == sorted(request.key for request in kept)


@pytest.mark.anyio
async def test_the_endpoint_and_session_index_is_created_once(
    mongo: AsyncMongoClient[MongoDocument], database: str
) -> None:
    store = MongoRawStore(mongo, database)

    await store.ensure_indexes()
    await store.ensure_indexes()

    indexes = await mongo[database][COLLECTION].index_information()
    assert indexes[ENDPOINT_SESSION_INDEX]["key"] == [("endpoint", 1), ("session_key", 1)]
    assert sorted(indexes) == ["_id_", ENDPOINT_SESSION_INDEX]
