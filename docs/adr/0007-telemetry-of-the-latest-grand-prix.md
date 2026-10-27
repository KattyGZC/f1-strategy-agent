# 0007. Telemetry of the latest settled Grand Prix, one session kept

- Status: Accepted
- Date: 2026-10-27

## Context

ADR 0006 stores car telemetry (`car_data`, `location`) on demand for one session given by its `session_key`. The session ingested in phase 1 was the 2024 Bahrain race (`9472`), chosen to measure sizes. The demo and the assistant should show the latest race, not one from two seasons ago, and finding its `session_key` by hand every weekend is a manual step that a scheduled job cannot take.

Size, from ADR 0006: the telemetry of one race is about 135 MB of BSON, and the free MongoDB tier is 512 MB (ADR 0004). A season without telemetry is 123.6 MB. Telemetry that only accumulates fills the tier in about three races.

OpenF1, read with curl on 2026-10-27:

- `sessions?date_end<2026-10-27T00:00:00+00:00&session_name=Race` answers 200 with 91 rows (32.6 KB), every one with `session_type` Race and `session_name` Race, across all seasons; the latest `date_end` is `11396` (2026 United States, 2026-10-25T22:00Z).
- Three of those rows have `is_cancelled` true.
- Sprints are `session_type` Race with `session_name` Sprint (`sessions?year=2026`: 6 rows), so filtering by session name keeps them out.
- With no Grand Prix before the cutoff (`date_end<2023-01-01`) the answer is 404 "No results found.", stored as an empty list (ADR 0006).

## Options

1. **Keep the explicit session only.** No code, but every refresh needs someone to look up the key, and telemetry still accumulates.
2. **Latest Grand Prix by default, telemetry of every session kept.** Automatic, but storage grows by about 135 MB per race until the tier is full.
3. **Latest Grand Prix by default, telemetry of one session kept.** Automatic and bounded: after the telemetry of a session is fully stored, the telemetry of every other session is deleted.

## Decision

Option 3. `make ingest-telemetry` with no `SESSION` stores the telemetry of the latest settled Grand Prix: not cancelled, not a sprint, and ended before the settled cutoff that the season index uses (`SESSION_SETTLE_H` ago, truncated to the hour). Races that end at the same instant are ordered by `session_key`, the higher one first. `SESSION=...` still picks another session. Either way, once the chosen session is complete, MongoDB keeps the telemetry of that session only. This replaces the telemetry part of ADR 0006; its season scope stands.

## Consequences

- Measured on 2026-10-27 (`make ingest-telemetry`, with `9472` stored): it chose `11396`, made 178 requests in 5 minutes 19 seconds, stored 176 telemetry documents (22 drivers, 153.3 MB of BSON) and deleted the 160 of `9472`. A rerun fetched and deleted nothing.
- Raw telemetry is deleted by whole sessions; a document is still never edited (ADR 0004). Every other endpoint is never deleted.
- The delete runs only after every telemetry request of the new session is stored, so a failed run keeps the previous session's telemetry and the store holds two sessions for a while (about 290 MB at the peak).
- `make ingest-telemetry SESSION=...` for an older race deletes the latest race's telemetry; the next run without `SESSION` brings it back.
- Each run in a new hour stores a new Grand Prix index (about 33 KB), like the season index of a season in progress.
- The collection gets an index on `endpoint` and `session_key`, the fields the delete filters on, created by the ingest command before each run.
- In production the scheduled job of phase 7 runs `make ingest YEAR=<current>` and then `make ingest-telemetry`.
- Anything derived from telemetry must be computed while it is stored or kept in the clean store; the raw telemetry of past races is gone.
