"""The first minute of a sampled race, as the API tests load it."""

from dataclasses import replace
from datetime import timedelta

from redis.asyncio import Redis

from f1_strategy.adapters.clean_store import PostgresCleanStore, connection_pool
from f1_strategy.application.transform import Load, Version
from f1_strategy.domain.clean import CleanSession, clean_session, content_hash
from f1_strategy.domain.replay import LapCompleted, timeline
from tests.postgres import CONNECT_TIMEOUT_S
from tests.samples import RACE, sample

SESSION = int(RACE)
WINDOW = timedelta(seconds=60)


def first_minute(session: CleanSession) -> CleanSession:
    """The session cut to its first minute of events, so a replay at 60x lasts one second."""
    cutoff = timeline(session).events[0].at + WINDOW
    ended_laps = {
        (event.payload.lap.driver_number, event.payload.lap.lap_number)
        for event in timeline(session).events
        if isinstance(event.payload, LapCompleted) and event.at < cutoff
    }
    return replace(
        session,
        laps=tuple(
            lap for lap in session.laps if (lap.driver_number, lap.lap_number) in ended_laps
        ),
        pits=tuple(row for row in session.pits if row.date < cutoff),
        intervals=tuple(row for row in session.intervals if row.date < cutoff),
        positions=tuple(row for row in session.positions if row.date < cutoff),
        race_control=tuple(row for row in session.race_control if row.date < cutoff),
        weather=tuple(row for row in session.weather if row.date < cutoff),
        overtakes=tuple(row for row in session.overtakes if row.date < cutoff),
        team_radio=tuple(row for row in session.team_radio if row.date < cutoff),
    )


SHORT_RACE = first_minute(clean_session(sample(RACE).raw()))
EVENTS = timeline(SHORT_RACE).events


async def load(postgres_uri: str, session: CleanSession) -> None:
    async with connection_pool(postgres_uri, 1, CONNECT_TIMEOUT_S) as pool:
        store = PostgresCleanStore(pool)
        version = Version("input-1", "1")
        async with store.claim(SESSION, version, EVENTS[0].at) as claim:
            assert claim is not None
            await claim.replace(Load(session, version, content_hash(session), EVENTS[0].at))


async def flush(redis_uri: str) -> None:
    client = Redis.from_url(redis_uri)
    await client.flushdb()
    await client.aclose()
