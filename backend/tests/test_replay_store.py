import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import replace

import pytest
import redis as sync_redis
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from f1_strategy.adapters.replay_events import wire_event
from f1_strategy.adapters.replay_store import RedisReplayStore
from f1_strategy.application.replay import ReplayState, StreamEntry
from f1_strategy.domain.clean import clean_session
from f1_strategy.domain.playback import Paused, Playing, ReplaySpeed
from f1_strategy.domain.replay import Event, timeline
from tests.samples import RACE, sample

pytestmark = pytest.mark.anyio

REPLAY = "replay-1"
PLAYING = ReplayState(9472, Playing(ReplaySpeed.X10, 12.5, 1_000.25))
BLOCK_S = 0.05
EVENTS: tuple[Event, ...] = timeline(clean_session(sample(RACE).raw())).events[:5]


@pytest.fixture
async def redis(redis_server_uri: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_server_uri)
    await client.flushdb()
    yield client
    await client.aclose()


def store(redis: Redis, max_active: int = 3, idle_ttl_s: int = 60) -> RedisReplayStore:
    return RedisReplayStore(redis, max_active, idle_ttl_s)


def appending(mark: str) -> Callable[[ReplayState], ReplayState]:
    return lambda state: replace(state, failure=f"{state.failure}{mark}")


def entries_of(events: tuple[Event, ...], first: int = 0) -> tuple[StreamEntry, ...]:
    return tuple(
        StreamEntry(f"0-{first + index + 1}", event.kind, wire_event(event).model_dump_json())
        for index, event in enumerate(events)
    )


@pytest.mark.parametrize(
    "state",
    [
        PLAYING,
        ReplayState(9468, Paused(ReplaySpeed.X1, 0.0)),
        ReplayState(9472, Paused(ReplaySpeed.X60, 3.75), "SessionNotLoadedError: gone"),
    ],
)
async def test_a_created_replay_reads_back_its_state(redis: Redis, state: ReplayState) -> None:
    replays = store(redis)

    assert await replays.create(REPLAY, state) is True
    assert await replays.state(REPLAY) == state


async def test_an_unknown_replay_has_no_state_stream_or_read(redis: Redis) -> None:
    replays = store(redis)

    assert await replays.state("missing") is None
    assert await replays.sent("missing") == 0
    assert await replays.read("missing", None, BLOCK_S) is None


async def test_no_replay_is_created_past_the_limit(redis: Redis) -> None:
    replays = store(redis, max_active=2)

    created = [await replays.create(f"replay-{n}", PLAYING) for n in range(3)]

    assert created == [True, True, False]
    assert await replays.state("replay-2") is None


async def test_simultaneous_creates_never_pass_the_limit(redis: Redis) -> None:
    replays = store(redis, max_active=3)

    created = await asyncio.gather(*(replays.create(f"replay-{n}", PLAYING) for n in range(10)))

    assert sorted(created) == [False] * 7 + [True] * 3


async def test_an_idle_replay_expires_and_frees_its_place(redis: Redis) -> None:
    replays = store(redis, max_active=1, idle_ttl_s=1)
    await replays.create(REPLAY, PLAYING)
    await replays.append(REPLAY, 0, EVENTS[:1])

    await asyncio.sleep(1.2)

    assert await replays.state(REPLAY) is None
    assert await replays.sent(REPLAY) == 0
    assert await replays.create("replay-2", PLAYING) is True


async def test_a_read_keeps_a_watched_replay_alive(redis: Redis) -> None:
    replays = store(redis, max_active=1, idle_ttl_s=1)
    await replays.create(REPLAY, PLAYING)
    await replays.append(REPLAY, 0, EVENTS[:1])

    for _ in range(4):
        await asyncio.sleep(0.4)
        assert await replays.read(REPLAY, None, BLOCK_S) is not None

    assert await replays.sent(REPLAY) == 1
    assert await replays.create("replay-2", PLAYING) is False


async def test_an_update_changes_the_state_and_keeps_its_expiry(redis: Redis) -> None:
    replays = store(redis, idle_ttl_s=60)
    await replays.create(REPLAY, PLAYING)

    updated = await replays.update(REPLAY, lambda state: replace(state, failure="boom"))

    assert updated == replace(PLAYING, failure="boom")
    assert await replays.state(REPLAY) == updated
    assert 0 < await redis.pttl(f"replay:{REPLAY}:state") <= 60_000


async def test_simultaneous_updates_all_apply(redis: Redis) -> None:
    replays = store(redis)
    await replays.create(REPLAY, ReplayState(9472, Paused(ReplaySpeed.X1, 0.0), ""))

    await asyncio.gather(*(replays.update(REPLAY, appending(mark)) for mark in "ab"))

    state = await replays.state(REPLAY)
    assert state is not None
    assert sorted(state.failure or "") == ["a", "b"]


async def test_updating_an_unknown_replay_changes_nothing(redis: Redis) -> None:
    assert await store(redis).update("missing", lambda state: state) is None
    assert await redis.exists("replay:missing:state") == 0


async def test_appended_events_read_back_in_order_with_their_ids(redis: Redis) -> None:
    replays = store(redis)
    await replays.create(REPLAY, PLAYING)
    await replays.append(REPLAY, 0, EVENTS[:2])
    await replays.append(REPLAY, 2, EVENTS[2:])

    read = await replays.read(REPLAY, None, BLOCK_S)

    assert read is not None
    assert read.state == PLAYING
    assert read.entries == entries_of(EVENTS)
    assert await replays.sent(REPLAY) == len(EVENTS)
    assert json.loads(read.entries[0].data)["kind"] == EVENTS[0].kind


async def test_a_read_after_an_id_returns_only_later_entries(redis: Redis) -> None:
    replays = store(redis)
    await replays.create(REPLAY, PLAYING)
    await replays.append(REPLAY, 0, EVENTS)

    read = await replays.read(REPLAY, "0-3", BLOCK_S)

    assert read is not None
    assert read.entries == entries_of(EVENTS[3:], first=3)


async def test_a_read_with_nothing_new_waits_then_returns_no_entries(redis: Redis) -> None:
    replays = store(redis)
    await replays.create(REPLAY, PLAYING)

    read = await replays.read(REPLAY, None, BLOCK_S)

    assert read is not None
    assert read.entries == ()


async def test_a_read_returns_an_entry_appended_while_it_waits(redis: Redis) -> None:
    replays = store(redis)
    await replays.create(REPLAY, PLAYING)
    reading = asyncio.create_task(replays.read(REPLAY, None, 5.0))
    await asyncio.sleep(0.1)

    await replays.append(REPLAY, 0, EVENTS[:1])

    read = await asyncio.wait_for(reading, timeout=2.0)
    assert read is not None
    assert read.entries == entries_of(EVENTS[:1])


@pytest.mark.parametrize("first_index", [0, 2])
async def test_an_append_that_does_not_continue_the_stream_is_refused(
    redis: Redis, first_index: int
) -> None:
    replays = store(redis)
    await replays.create(REPLAY, PLAYING)
    await replays.append(REPLAY, 0, EVENTS[:1])

    with pytest.raises(ResponseError, match="the stream holds 1 events"):
        await replays.append(REPLAY, first_index, EVENTS[1:2])

    assert await replays.sent(REPLAY) == 1


async def test_an_append_to_a_gone_replay_is_refused(redis: Redis) -> None:
    with pytest.raises(ResponseError, match="the replay is gone"):
        await store(redis).append("missing", 0, EVENTS[:1])

    assert await redis.exists("replay:missing:events") == 0


async def test_one_owner_holds_a_lease_until_it_releases_it(redis: Redis) -> None:
    replays = store(redis)

    held = [
        await replays.hold_lease(REPLAY, "a", 5.0),
        await replays.hold_lease(REPLAY, "b", 5.0),
        await replays.hold_lease(REPLAY, "a", 5.0),
    ]
    await replays.release_lease(REPLAY, "b")
    still_held = await replays.hold_lease(REPLAY, "b", 5.0)
    await replays.release_lease(REPLAY, "a")

    assert held == [True, False, True]
    assert still_held is False
    assert await replays.hold_lease(REPLAY, "b", 5.0) is True


async def test_a_lease_its_owner_stops_renewing_expires(redis: Redis) -> None:
    replays = store(redis)
    await replays.hold_lease(REPLAY, "a", 0.2)

    await asyncio.sleep(0.4)

    assert await replays.hold_lease(REPLAY, "b", 5.0) is True


async def test_an_update_that_keeps_losing_the_race_gives_up(
    redis: Redis, redis_server_uri: str
) -> None:
    replays = store(redis)
    await replays.create(REPLAY, PLAYING)
    rival = sync_redis.Redis.from_url(redis_server_uri)

    def change_raced_by_another_writer(state: ReplayState) -> ReplayState:
        rival.set(f"replay:{REPLAY}:state", rival.get(f"replay:{REPLAY}:state") or b"")
        return replace(state, failure="lost")

    with pytest.raises(RuntimeError, match="changed 5 times"):
        await replays.update(REPLAY, change_raced_by_another_writer)

    rival.close()
    assert await replays.state(REPLAY) == PLAYING
