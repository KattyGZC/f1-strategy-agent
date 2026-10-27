# 0006. Raw data scope: Race and Qualifying by season, telemetry by session

- Status: Accepted
- Date: 2026-10-26

## Context

ADR 0004 left open what raw data is kept, until the size of one season was measured against the 512 MB of the free MongoDB tier. Phase 1 measured the OpenF1 responses of the 2024 Bahrain race (`session_key=9472`) with curl on 2026-10-26:

- `intervals` is 4.2 MB of JSON, `laps` 564 KB, and the other per-session endpoints about 250 KB together.
- `car_data` and `location` for the whole session answer 422 ("You're likely asking for too much data at once"). Per driver they are 5.7 MB and 4.5 MB, about 200 MB per race for 20 drivers.
- `starting_grid` belongs to the qualifying session (`9468`: 20 rows); asked of the race it is an empty result.
- An empty result is `404 {"detail": "No results found."}`, not `[]`.
- Telemetry starts about an hour before the session's `date_start` (laps to the grid) and the race falls inside `[date_start, date_end]`.

The simulator and the assistant work from laps, stints, pit stops, intervals, weather and race control. The replay (phase 3) may want car positions for one demo race.

## Options

1. **Every endpoint of every session.** Complete, but about 5 GB per season with telemetry: it does not fit the free tier, and at 30 requests per minute it takes hours.
2. **Race and Qualifying sessions by season, without telemetry; telemetry on demand for one session.** Fits the free tier; the starting grid comes from qualifying.
3. **Race only.** Smallest, but loses the starting grid and qualifying pace.

## Decision

Option 2. `make ingest YEAR=...` stores every per-session endpoint of a finished season's Race and Qualifying sessions (sprints included, since OpenF1 types them Race and Qualifying). `make ingest-telemetry SESSION=...` stores `car_data` and `location` of one session, per driver, in fixed windows from `date_start` to `date_end`.

## Consequences

- Only finished seasons are ingested (`year` before the current one). The season index (`sessions?year=`) is stored once, so ingesting a season in progress would freeze its future sessions as missing.
- Telemetry before `date_start` (laps to the grid) is not fetched.
- Telemetry windows are 30 minutes (`TELEMETRY_WINDOW_MIN`): about 1.1 MB per driver and window, well under MongoDB's 16 MB document limit, so a long or red-flagged race still fits.
- An empty result is stored as an empty list, so a rerun does not ask again.
- Measured on the full 2024 season (`make ingest YEAR=2024`, 2026-10-26): 60 sessions, 632 requests, 21 minutes; 123.6 MB of BSON data, 23.6 MB of compressed storage, largest document 4.6 MB (`collStats`). Counting the uncompressed size, the conservative reading of the 512 MB tier, about four seasons fit; which seasons go to production is decided in phase 7.
- Measured on one session (`make ingest-telemetry SESSION=9472`): 162 requests in 5 minutes; `car_data` 80 documents and 76.7 MB, `location` 80 documents and 58.8 MB. One race of telemetry weighs about as much as a whole season without it.
- Throughput was 30 requests per minute while responses were small and about 15 while the 4 MB `intervals` responses were in flight: latency, not the rate limit, sets the pace at a concurrency of 3.
