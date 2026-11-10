"""The API over a real PostgreSQL and Redis, holding the first minute of a sampled race."""

import asyncio
from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from f1_strategy.adapters.http.app import create_app
from f1_strategy.adapters.http.services import ApiServices, api_services
from f1_strategy.adapters.migrate import upgrade
from f1_strategy.adapters.settings import ApiSettings
from tests.http.api import SHORT_RACE, flush, load
from tests.postgres import CONNECT_TIMEOUT_S, fresh_database


@pytest.fixture
def settings(postgres_server_uri: str, redis_server_uri: str) -> ApiSettings:
    postgres_uri = fresh_database(postgres_server_uri)
    upgrade(postgres_uri, CONNECT_TIMEOUT_S)
    asyncio.run(load(postgres_uri, SHORT_RACE), loop_factory=asyncio.SelectorEventLoop)
    asyncio.run(flush(redis_server_uri))
    return ApiSettings(
        postgres_uri=SecretStr(postgres_uri),
        postgres_connect_timeout_s=CONNECT_TIMEOUT_S,
        postgres_pool_size=2,
        redis_uri=SecretStr(redis_server_uri),
        redis_max_connections=8,
        redis_timeout_s=5,
        replay_max_active=2,
        replay_idle_ttl_s=60,
        replay_tick_s=0.02,
        replay_lease_s=1,
    )


@pytest.fixture
def client(settings: ApiSettings) -> Iterator[TestClient]:
    def services() -> AbstractAsyncContextManager[ApiServices]:
        return api_services(settings)

    # psycopg's async driver needs the selector loop, also in the test client's thread.
    options = {"loop_factory": asyncio.SelectorEventLoop}
    with TestClient(create_app(services), backend_options=options) as test_client:
        yield test_client
