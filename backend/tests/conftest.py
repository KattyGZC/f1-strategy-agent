from collections.abc import Iterator

import pytest
from testcontainers.community.mongodb import MongoDbContainer


@pytest.fixture(scope="session")
def mongo_uri() -> Iterator[str]:
    with MongoDbContainer("mongo:8") as container:
        yield container.get_connection_url()
