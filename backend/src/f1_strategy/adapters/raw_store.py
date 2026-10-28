from collections.abc import Sequence
from contextlib import suppress
from datetime import datetime

from pymongo import ASCENDING, AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import DuplicateKeyError

from f1_strategy.domain.openf1 import TELEMETRY_ENDPOINTS, JsonObject, RawRequest, RawResponse

COLLECTION = "openf1_responses"
ENDPOINT_SESSION_INDEX = "endpoint_session_key"

type MongoDocument = dict[str, object]


class MongoRawStore:
    def __init__(self, client: AsyncMongoClient[MongoDocument], database: str) -> None:
        self._responses: AsyncCollection[MongoDocument] = client[database][COLLECTION]

    async def ensure_indexes(self) -> None:
        await self._responses.create_index(
            [("endpoint", ASCENDING), ("session_key", ASCENDING)], name=ENDPOINT_SESSION_INDEX
        )

    async def contains(self, request: RawRequest) -> bool:
        return await self._responses.count_documents({"_id": request.key}, limit=1) == 1

    async def rows(self, request: RawRequest) -> list[JsonObject] | None:
        document = await self._responses.find_one({"_id": request.key}, {"rows": 1})
        if document is None:
            return None
        rows = document["rows"]
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise TypeError(f"stored rows of {request.key} are not a list of objects")
        return rows

    async def fetched_at(self, requests: Sequence[RawRequest]) -> dict[str, datetime]:
        keys = [request.key for request in requests]
        cursor = self._responses.find({"_id": {"$in": keys}}, {"fetched_at": 1})
        stamps: dict[str, datetime] = {}
        async for document in cursor:
            fetched_at = document["fetched_at"]
            if not isinstance(fetched_at, datetime) or fetched_at.tzinfo is None:
                raise TypeError(f"fetched_at of {document['_id']} is not an aware datetime")
            stamps[str(document["_id"])] = fetched_at
        return stamps

    async def put(self, response: RawResponse) -> None:
        request = response.request
        with suppress(DuplicateKeyError):
            await self._responses.insert_one(
                {
                    "_id": request.key,
                    "endpoint": str(request.endpoint),
                    "params": {str(name): value for name, value in request.params},
                    "session_key": request.session_key,
                    "rows": response.rows,
                    "fetched_at": response.fetched_at,
                }
            )

    async def delete_telemetry_except(self, session_key: int) -> int:
        result = await self._responses.delete_many(
            {
                "endpoint": {"$in": [str(endpoint) for endpoint in TELEMETRY_ENDPOINTS]},
                "session_key": {"$ne": session_key},
            }
        )
        return result.deleted_count
