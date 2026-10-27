# 0006. Raw data scope: settled Race and Qualifying sessions by season, telemetry by session

- Status: Accepted
- Date: 2026-10-26

## Context

ADR 0004 left open what raw data is kept, until the size of one season was measured against the 512 MB of the free MongoDB tier. Phase 1 measured the OpenF1 responses of the 2024 Bahrain race (`session_key=9472`) with curl on 2026-10-26:

- `intervals` is 4.2 MB of JSON, `laps` 564 KB, and the other per-session endpoints about 250 KB together.
- `car_data` and `location` for the whole session answer 422 ("You're likely asking for too much data at once"). Per driver they are 5.7 MB and 4.5 MB, about 200 MB per race for 20 drivers.
- `starting_grid` belongs to the qualifying session (`9468`: 20 rows); asked of the race it is an empty result.
- An empty result is `404 {"detail": "No results found."}`, not `[]`.
- Telemetry starts about an hour before the session's `date_start` (laps to the grid) and the race falls inside `[date_start, date_end]`.
- `sessions?year=2026&date_end<2026-10-20T00:00:00+00:00` returns only the sessions that ended before that instant (101 of 131).
- openf1.org: "Data is considered live from 30 minutes before a session starts until 30 minutes after it ends", and session results become "available a few minutes after the official results are published on the official Formula 1 website". The 2026 United States race (`11396`), read 29 hours after it ended, had 1166 laps and 22 results.

The simulator and the assistant work from laps, stints, pit stops, intervals, weather and race control, and the assistant should answer about the latest race, not only about past seasons. The replay (phase 3) may want car positions for one demo race.

Raw documents are written once and never updated (ADR 0004), so a session stored before OpenF1 has its final data keeps the incomplete version.

## Options

1. **Every endpoint of every session.** Complete, but about 5 GB per season with telemetry: it does not fit the free tier, and at 30 requests per minute it takes hours.
2. **Race and Qualifying sessions by season, without telemetry; telemetry on demand for one session.** Fits the free tier; the starting grid comes from qualifying.
3. **Race only.** Smallest, but loses the starting grid and qualifying pace.

## Decision

Option 2. `make ingest YEAR=...` stores every per-session endpoint of a season's Race and Qualifying sessions (sprints included, since OpenF1 types them Race and Qualifying) once each session has settled: it ended at least `SESSION_SETTLE_H` hours ago. `make ingest-telemetry SESSION=...` stores `car_data` and `location` of one settled session, per driver, in fixed windows from `date_start` to `date_end`.

## Consequences

- The season index is `sessions?year=Y&date_end<cutoff`, with cutoff = the earlier of now minus the settle time and the start of year Y+1, truncated to the hour. A settled season always gets the same key; a season in progress gets a new index on each run, which lists the newly settled sessions without rewriting any document. Sessions are also filtered by the cutoff in the domain, so a session that has not settled is never stored as empty.
- The settle time defaults to 6 hours. The 30 minutes until data is historical are documented; the rest is a margin for the official classification and same-day penalties, not a measured value. A later correction (a penalty days after the race) is not picked up.
- A season in progress is refreshed by running the same command again; in production that is a scheduled job (phase 7).
- Telemetry before `date_start` (laps to the grid) is not fetched.
- Telemetry windows are 30 minutes (`TELEMETRY_WINDOW_MIN`): about 1.1 MB per driver and window, well under MongoDB's 16 MB document limit, so a long or red-flagged race still fits.
- An empty result is stored as an empty list, so a rerun does not ask again.
- Measured on the full 2024 season (`make ingest YEAR=2024`, 2026-10-26): 60 sessions, 632 requests, 21 minutes; 123.6 MB of BSON data, 23.6 MB of compressed storage, largest document 4.6 MB (`collStats`). Counting the uncompressed size, the conservative reading of the 512 MB tier, about four seasons fit; which seasons go to production is decided in phase 7.
- Measured on one session (`make ingest-telemetry SESSION=9472`): 162 requests in 5 minutes; `car_data` 80 documents and 76.7 MB, `location` 80 documents and 58.8 MB. One race of telemetry weighs about as much as a whole season without it.
- Throughput was 30 requests per minute while responses were small and about 15 while the 4 MB `intervals` responses were in flight: latency, not the rate limit, sets the pace at a concurrency of 3.
