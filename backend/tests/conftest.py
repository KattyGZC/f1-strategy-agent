from collections.abc import Iterator

import pytest
from sqlalchemy import make_url
from testcontainers.community.mongodb import MongoDbContainer
from testcontainers.community.postgres import PostgresContainer


@pytest.fixture(scope="session")
def mongo_uri() -> Iterator[str]:
    with MongoDbContainer("mongo:8") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def postgres_server_uri() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:pg17", driver=None) as container:
        # Docker Desktop on Windows accepts "localhost" on ::1 and never answers, so a connection
        # waits out its whole timeout before falling back to IPv4 (2026-10-27).
        url = make_url(container.get_connection_url())
        yield url.set(host="127.0.0.1").render_as_string(hide_password=False)
