"""The replay services the API serves, built once per process from the settings."""

import asyncio
import os
import secrets
import socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from f1_strategy.adapters.clean_store import PostgresReplayRows, connection_pool
from f1_strategy.adapters.replay_store import RedisReplayStore, redis_client
from f1_strategy.adapters.settings import ApiSettings
from f1_strategy.application.replay import (
    ControlReplay,
    ProduceReplay,
    ReplayPolicy,
    ReplayProducers,
    StartReplay,
    WatchReplay,
)

REPLAY_ID_BYTES = 16


@dataclass(frozen=True)
class ReplayServices:
    start: StartReplay
    control: ControlReplay
    watch: WatchReplay


class SystemClock:
    def __call__(self) -> float:
        return time.time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def new_replay_id() -> str:
    """Unguessable: whoever knows a replay's id can control it."""
    return secrets.token_urlsafe(REPLAY_ID_BYTES)


def process_owner() -> str:
    """Names this process in the producer leases it holds."""
    return f"{socket.gethostname()}-{os.getpid()}"


@asynccontextmanager
async def replay_services(settings: ApiSettings) -> AsyncIterator[ReplayServices]:
    """The services, open for the block; leaving it stops this process's producers first."""
    pool = connection_pool(
        settings.postgres_uri.get_secret_value(),
        max_size=settings.postgres_pool_size,
        connect_timeout_s=settings.postgres_connect_timeout_s,
    )
    redis = redis_client(
        settings.redis_uri.get_secret_value(),
        settings.redis_max_connections,
        settings.redis_timeout_s,
    )
    clock = SystemClock()
    policy = ReplayPolicy(tick_s=settings.replay_tick_s, lease_s=settings.replay_lease_s)
    rows = PostgresReplayRows(pool)
    store = RedisReplayStore(redis, settings.replay_max_active, settings.replay_idle_ttl_s)
    producers = ReplayProducers(
        ProduceReplay(rows, store, policy, clock, owner=process_owner()), store
    )
    try:
        async with pool:
            try:
                yield ReplayServices(
                    start=StartReplay(rows, store, producers, clock, new_replay_id),
                    control=ControlReplay(store, clock),
                    watch=WatchReplay(store, producers, policy),
                )
            finally:
                await producers.aclose()
    finally:
        await redis.aclose()
