"""Replays in Redis: each replay's state, its stream of events and its producer lease (ADR 0009).

Every step that must not interleave with another runs as one Lua script, which Redis runs
atomically. Expiry is measured from the last read of a viewer: a replay nobody watches for
`idle_ttl_s` disappears with its stream.
"""

from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from redis.asyncio import BlockingConnectionPool, Redis
from redis.asyncio.client import Pipeline
from redis.exceptions import WatchError

from f1_strategy.adapters.replay_events import wire_event
from f1_strategy.application.replay import ReplayState, StreamEntry, StreamRead
from f1_strategy.domain.playback import Paused, Playback, PlaybackStatus, Playing, ReplaySpeed
from f1_strategy.domain.replay import Event, EventKind

ACTIVE_KEY = "replays:active"
# Optimistic updates retry when another writer changed the state in between. The only writers
# are a viewer's controls and a producer's failure, so a conflict is rare and five attempts
# leave room for it; past that the update fails loud.
UPDATE_ATTEMPTS = 5
MILLISECONDS_PER_S = 1000
# What APPEND returns, appending nothing, for a replay that is gone.
GONE = -1

# Drops replays whose idle time ran out, then adds this one unless the limit is reached.
# Time comes from the Redis server, so every backend process measures the same expiry.
CREATE = """
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then
    return 0
end
redis.call('ZADD', KEYS[1], now_ms + tonumber(ARGV[2]), ARGV[3])
redis.call('SET', KEYS[2], ARGV[4], 'PX', ARGV[2])
return 1
"""

# Appends only right after the last entry, so a producer that resumes, or two that briefly
# overlap, can neither leave a gap nor send an event twice.
APPEND = """
local ttl = redis.call('PTTL', KEYS[1])
if ttl < 0 then
    return -1
end
local held = redis.call('XLEN', KEYS[2])
if held ~= tonumber(ARGV[1]) then
    return redis.error_reply('the stream holds ' .. held .. ' events, not ' .. ARGV[1])
end
for i = 2, #ARGV, 2 do
    held = held + 1
    redis.call('XADD', KEYS[2], '0-' .. held, 'kind', ARGV[i], 'data', ARGV[i + 1])
end
redis.call('PEXPIRE', KEYS[2], ttl)
return held
"""

# A viewer's read pushes the replay's expiry back and returns its state, in one step so the
# replay cannot expire in between; nil when it is already gone.
TOUCH = """
if redis.call('PEXPIRE', KEYS[1], ARGV[1]) == 0 then
    return false
end
redis.call('PEXPIRE', KEYS[2], ARGV[1])
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
redis.call('ZADD', KEYS[3], 'XX', now_ms + tonumber(ARGV[1]), ARGV[2])
return redis.call('GET', KEYS[1])
"""

# Removes the replay and gives its place back in one step, so no create sees it half gone.
DELETE = """
local existed = redis.call('DEL', KEYS[1])
redis.call('DEL', KEYS[2], KEYS[3])
redis.call('ZREM', KEYS[4], ARGV[1])
return existed
"""

HOLD_LEASE = """
local holder = redis.call('GET', KEYS[1])
if holder and holder ~= ARGV[1] then
    return 0
end
redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2])
return 1
"""

RELEASE_LEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('DEL', KEYS[1])
end
return 0
"""


# The shape of an XREAD reply on a client that does not decode responses.
_XREAD_REPLY = TypeAdapter(list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]])


class _StoredPlaying(BaseModel):
    status: Literal[PlaybackStatus.PLAYING] = PlaybackStatus.PLAYING
    speed: ReplaySpeed
    session_s: float
    wall_s: float


class _StoredPaused(BaseModel):
    status: Literal[PlaybackStatus.PAUSED] = PlaybackStatus.PAUSED
    speed: ReplaySpeed
    session_s: float


class _StoredState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_key: int
    playback: Annotated[_StoredPlaying | _StoredPaused, Field(discriminator="status")]
    failure: str | None


def redis_client(uri: str, max_connections: int, timeout_s: float) -> Redis:
    """A client whose pool waits up to `timeout_s` for a free connection instead of opening more
    than `max_connections`; close it with `aclose`."""
    pool = BlockingConnectionPool.from_url(
        uri, max_connections=max_connections, timeout=timeout_s, socket_connect_timeout=timeout_s
    )
    return Redis.from_pool(pool)


class RedisReplayStore:
    def __init__(self, redis: Redis, max_active: int, idle_ttl_s: int) -> None:
        self._redis = redis
        self._max_active = max_active
        self._idle_ttl_ms = idle_ttl_s * MILLISECONDS_PER_S
        self._create = redis.register_script(CREATE)
        self._append = redis.register_script(APPEND)
        self._delete = redis.register_script(DELETE)
        self._touch = redis.register_script(TOUCH)
        self._hold_lease = redis.register_script(HOLD_LEASE)
        self._release_lease = redis.register_script(RELEASE_LEASE)

    async def create(self, replay_id: str, state: ReplayState) -> bool:
        created = await self._create(
            keys=[ACTIVE_KEY, _state_key(replay_id)],
            args=[self._max_active, self._idle_ttl_ms, replay_id, _encode(state)],
        )
        return bool(created)

    async def state(self, replay_id: str) -> ReplayState | None:
        stored = await self._redis.get(_state_key(replay_id))
        return None if stored is None else _decode(stored)

    async def update(
        self, replay_id: str, change: Callable[[ReplayState], ReplayState]
    ) -> ReplayState | None:
        key = _state_key(replay_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            for _ in range(UPDATE_ATTEMPTS):
                with suppress(WatchError):
                    return await _change_once(pipe, key, change)
        raise RuntimeError(f"replay {replay_id} changed {UPDATE_ATTEMPTS} times while updated")

    async def sent(self, replay_id: str) -> int:
        return int(await self._redis.xlen(_events_key(replay_id)))

    async def append(self, replay_id: str, first_index: int, events: Sequence[Event]) -> bool:
        encoded: list[str | int] = [first_index]
        for event in events:
            encoded.extend([event.kind.value, wire_event(event).model_dump_json()])
        held = await self._append(
            keys=[_state_key(replay_id), _events_key(replay_id)], args=encoded
        )
        return int(held) != GONE

    async def delete(self, replay_id: str) -> bool:
        keys = [_state_key(replay_id), _events_key(replay_id), _lease_key(replay_id), ACTIVE_KEY]
        existed = await self._delete(keys=keys, args=[replay_id])
        return bool(existed)

    async def read(self, replay_id: str, after: str | None, block_s: float) -> StreamRead | None:
        keys = [_state_key(replay_id), _events_key(replay_id), ACTIVE_KEY]
        stored = await self._touch(keys=keys, args=[self._idle_ttl_ms, replay_id])
        if stored is None:
            return None
        reply = await self._redis.xread(
            {_events_key(replay_id): after or "0-0"},
            # BLOCK 0 waits forever; the shortest wait Redis takes is one millisecond.
            block=max(1, round(block_s * MILLISECONDS_PER_S)),
        )
        entries = tuple(
            _entry(entry_id, fields)
            for _, stream in _XREAD_REPLY.validate_python(reply)
            for entry_id, fields in stream
        )
        return StreamRead(_decode(stored), entries)

    async def hold_lease(self, replay_id: str, owner: str, lease_s: float) -> bool:
        held = await self._hold_lease(
            keys=[_lease_key(replay_id)], args=[owner, round(lease_s * MILLISECONDS_PER_S)]
        )
        return bool(held)

    async def release_lease(self, replay_id: str, owner: str) -> None:
        await self._release_lease(keys=[_lease_key(replay_id)], args=[owner])


async def _change_once(
    pipe: Pipeline, key: str, change: Callable[[ReplayState], ReplayState]
) -> ReplayState | None:
    """Raises `WatchError` when another writer changed the key between the read and the write."""
    await pipe.watch(key)
    stored = await pipe.get(key)
    if stored is None:
        return None
    changed = change(_decode(stored))
    pipe.multi()  # type: ignore[no-untyped-call]  # unannotated in redis-py 8
    pipe.set(key, _encode(changed), keepttl=True)
    await pipe.execute()
    return changed


def _state_key(replay_id: str) -> str:
    return f"replay:{replay_id}:state"


def _events_key(replay_id: str) -> str:
    return f"replay:{replay_id}:events"


def _lease_key(replay_id: str) -> str:
    return f"replay:{replay_id}:lease"


def _entry(entry_id: bytes, fields: dict[bytes, bytes]) -> StreamEntry:
    return StreamEntry(
        entry_id.decode(), EventKind(fields[b"kind"].decode()), fields[b"data"].decode()
    )


def _encode(state: ReplayState) -> str:
    return _StoredState(
        session_key=state.session_key,
        playback=_stored_playback(state.playback),
        failure=state.failure,
    ).model_dump_json()


def _stored_playback(playback: Playback) -> _StoredPlaying | _StoredPaused:
    if isinstance(playback, Paused):
        return _StoredPaused(speed=playback.speed, session_s=playback.session_s)
    return _StoredPlaying(
        speed=playback.speed, session_s=playback.session_s, wall_s=playback.wall_s
    )


def _decode(stored: bytes | str) -> ReplayState:
    state = _StoredState.model_validate_json(stored)
    stored_playback = state.playback
    playback: Playback = (
        Paused(stored_playback.speed, stored_playback.session_s)
        if isinstance(stored_playback, _StoredPaused)
        else Playing(stored_playback.speed, stored_playback.session_s, stored_playback.wall_s)
    )
    return ReplayState(state.session_key, playback, state.failure)
