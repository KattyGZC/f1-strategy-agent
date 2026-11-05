# 0009. Replay from the clean model, through Redis Streams, to the browser over SSE

- Status: Proposed
- Date: 2026-10-29

## Context

Phase 3 replays a stored session as if live (ADR 0001): the user picks a session, plays it at 1x or faster, pauses it, changes its speed and jumps to a lap, and the browser shows the timing as it would have looked. The same session replayed twice must give the same stream.

Clean data has one owner, the clean model (ADR 0008). Telemetry (`car_data`, `location`) is not in it: it stays raw in MongoDB, for the latest Grand Prix only (ADR 0007).

Measured on the 2024 Bahrain race (`session_key` 9472) and the 2024 season in the clean model (psql, 2026-10-29):

- Rows of 9472 with an instant: `interval` 29,844, `lap` 1,129, `position` 698, `overtake` 414, `weather` 157, `team_radio` 137, `race_control` 71, `pit` 43. About 32,500 events over 2 h 35 min, from an hour before the start to 40 minutes after the flag.
- A lap carries when it started (`date_start`) and its duration, not when it ended. In race sessions, `date_start + lap_duration` equals the next lap's `date_start` within 0.5 s in 28,360 of 28,416 consecutive pairs. 100 race laps have no duration (51 of them lap 1), and 21 have no `date_start`.
- A stint has no instant, only `lap_start` and `lap_end`. Consecutive stints may share one lap (ADR 0008).
- Instants repeat within a table: 235 in `position` of 9472, 85 across `race_control` of the season.
- 61 race laps of the season are covered by no stint; 2,099 laps are covered by two (the shared boundary lap).

## Options

Source:

1. **The clean model.** Typed, validated, the owner of clean data. No telemetry.
2. **The raw store.** Has telemetry, but replays data no rule has validated, and goes around the owner.

Queue between the producer and the consumers:

1. **An in-process `asyncio.Queue`.** Simplest; nothing survives a restart, and a second backend process cannot read it.
2. **PostgreSQL `LISTEN/NOTIFY`.** No new service; payloads are capped at 8000 bytes and nothing is kept for a consumer that reconnects.
3. **Redis Streams.** Ordered, kept until trimmed or expired, read from any id, so a consumer that reconnects resumes where it stopped. One more service.

Transport to the browser:

1. **WebSocket.** Two-way. Reconnection and resume are written by hand, and its messages are not in the OpenAPI schema, so their TypeScript types would be written by hand.
2. **Server-Sent Events, with controls as REST endpoints.** One-way, which is all a replay needs; the browser reconnects on its own and sends `Last-Event-ID`. Controls are ordinary routes in the generated client.

Who watches a replay:

1. **One replay per session, shared like a broadcast.** Cheap, but nobody can pause or change the speed alone.
2. **One replay per viewer**, bounded in number and expired when idle.

Where the producer runs:

1. **A separate worker service.** Scales apart, but it is another always-on service on a free hosting tier.
2. **A task in the backend process**, owned by its lifespan, with the replay's state in Redis so it resumes after a restart.

## Decision

A replay reads only the clean model. A pure domain function turns a session's rows into one ordered timeline; an application use case paces it with an injected clock and appends it to a Redis stream per replay; the browser reads that stream over SSE and controls the replay through REST. Each viewer starts their own replay. The producer is a task in the backend process. Telemetry is not replayed.

## Consequences

- The timeline is a function of the session's clean rows only: no clock, no random, no Redis. It is tested in the domain, and the same session always gives the same list.
- An event's instant is its row's `date`; for a lap, `date_start + lap_duration`. A lap without either has no instant in the source and is not emitted. It is not placed by guessing, and the count of skipped laps is part of the timeline so it can be shown.
- A lap event carries the compound and tyre age of its stint, joined by lap number (`tyre_age_at_start + lap_number - lap_start`). Where two stints share a lap, the higher `stint_number` wins. A lap no stint covers (61 race laps in 2024) carries no compound and no age. Stints are not events of their own.
- Order: instant, then event kind in a fixed rank (race control, weather, pit, lap, position, interval, overtake, team radio), then the row's key within its kind: `seq` for race control, driver and lap number for a lap, the two drivers for an overtake, the driver for the rest. Each of these keys is unique in the clean model, so no two events tie. Event kinds are one enum.
- The content of a replay never depends on pacing: pause and speed change when an event is sent, not which events or in what order. A stream entry's id is `<generation>-<n>`, where n is the event's position in the timeline counting from 1 (Redis reserves `0-0`) and generation counts seeks, so ids only grow and `Last-Event-ID` resumes exactly. The SSE id of an event is its stream id.
- A seek to lap N starts a new generation at the earliest `date_start` of lap N in the session: the stream gets a reset event, then the timeline from the start up to that instant without pacing, so the browser rebuilds its state from events alone, then paced events from there.
- Speeds are a closed set, defined once. The replay clock starts at the first event's instant.
- The replay's state (session, speed, status, the anchor between session time and wall time) lives in Redis next to its stream. A producer holds a lease on its replay in Redis; if the process dies, the lease expires and the next request for that replay starts a producer that resumes from the last id in the stream.
- Bounds are configured: the number of active replays, the idle time after which a replay and its stream expire, and the lease length. A replay over the limit is refused, not queued.
- A producer re-reads its replay's state every tick (`REPLAY_TICK_S`, shorter than the lease) and renews its lease, so a pause or a new speed applied through any process takes effect within a tick. Controls change the state atomically in the store, so two at once do not lose one.
- Pacing is pure (`domain/playback.py`). An event is due when its wall instant has come, computed by the same function the producer waits with, so float rounding cannot leave an event whose wait is over unsent.
- A producer that fails records the error on its replay, where the viewer reads it; the other replays keep running, and a failed replay is not produced again.
- The store enforces the limit on active replays when it creates one, so the check and the insert cannot race.
- A replay of the 2024 Bahrain race holds 32,493 events, 6.2 MB in Redis (`MEMORY USAGE`, 2026-11-04), so the number of active replays is what sizes Redis: the default of 10 needs about 62 MB.
- The event schemas reach the generated TypeScript client because the SSE route is annotated with the event models; FastAPI leaves out of OpenAPI a route that only yields `ServerSentEvent`, which is what carries the id.
- The frontend folds events into what it shows. It does not compute lap times, gaps or strategy (`AGENTS.md`); every number it shows came in an event.
- Redis runs in `infra/compose.yaml` and in CI; its adapter is tested against a real container. The Redis client is imported by one adapter module.
- Replaying telemetry needs it in the clean model first. That is a separate decision.
