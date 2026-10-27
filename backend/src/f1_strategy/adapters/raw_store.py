from contextlib import suppress

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import DuplicateKeyError

from f1_strategy.domain.openf1 import JsonObject, RawRequest, RawResponse

COLLECTION = "openf1_responses"

type MongoDocument = dict[str, object]


class MongoRawStore:
    def __init__(self, client: AsyncMongoClient[MongoDocument], database: str) -> None:
        self._responses: AsyncCollection[MongoDocument] = client[database][COLLECTION]

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
