import asyncio
from collections.abc import Iterator

import pytest
from hypothesis import settings
from sqlalchemy import make_url
from testcontainers.community.mongodb import MongoDbContainer
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

# The same examples on every run and machine, so a red property reproduces as it was seen.
settings.register_profile("deterministic", derandomize=True, database=None)
settings.load_profile("deterministic")


@pytest.fixture
def anyio_backend() -> tuple[str, dict[str, object]]:
    # psycopg's async driver cannot run on Windows' default proactor loop; the selector loop is
    # the default everywhere else, so every platform runs the same loop.
    return ("asyncio", {"loop_factory": asyncio.SelectorEventLoop})


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


@pytest.fixture(scope="session")
def redis_server_uri() -> Iterator[str]:
    with RedisContainer("redis:8") as container:
        yield f"redis://127.0.0.1:{container.get_exposed_port(container.port)}/0"
