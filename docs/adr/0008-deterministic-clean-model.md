# 0008. A deterministic clean model: one transaction per session, replaced whole

- Status: Accepted
- Date: 2026-10-27

## Context

Phase 2 turns the raw OpenF1 responses in MongoDB (ADR 0004) into a normalized PostgreSQL schema that the simulator and the assistant read. The clean data must be deterministic: the same raw documents and the same transform give the same rows, whatever the number of runs, the order of the sessions, the number of workers or the retries. It must also keep its integrity: a reader never sees half a session, and data the schema does not describe is rejected, not guessed.

In production nobody runs commands by hand. ADR 0003 deploys on merge, and ADRs 0006 and 0007 leave the refresh of the season in progress to a scheduled job (phase 7). The transform must therefore start on its own after an ingest, survive a process killed in the middle of a session, pick up again on the next run without a person, and leave a record that an alert can read.

What the raw store guarantees: documents are written once and never edited, keyed by `endpoint` + query params + `session_key` (ADR 0004), and the domain knows every request of a session (`session_requests`), so it can tell when a session's raw data is complete.

Measured on the 2024 season (`make ingest YEAR=2024`, then a profile of every stored row, 2026-10-27; the per-endpoint numbers are in the devlog of this session):

- Rows: `intervals` 613,428, `position` 51,876, `laps` 38,005, `weather` 6,523, `overtakes` 5,969, `team_radio` 4,595, `stints` 4,077, `race_control` 3,774, `pit` 3,472, `drivers` 1,220, `session_result` 1,197, `starting_grid` 599.
- Every candidate natural key is unique (`laps` by session, driver and lap; `intervals` and `position` by session, driver and date; and so on), except `race_control`: 85 instants carry more than one message.
- Values that are not one type: `gap_to_leader` is a number, null or a string `"+N LAP(S)"`; `interval` is a number, null or `"+1 LAP"`; in qualifying, `session_result.duration` and `gap_to_leader` are lists of three (one per phase).
- Nulls the schema must allow: lap and sector durations, speeds, `laps.date_start` (51), `stints.lap_start` and `lap_end` (16 stints of drivers who never ran), `session_result.position` (57, of which 4 have no DNF, DNS or DSQ flag).
- Closed sets seen: compounds `SOFT MEDIUM HARD INTERMEDIATE WET UNKNOWN`; flags, race control categories and scopes as listed in the devlog.
- Consecutive stints of a driver overlap by exactly one lap in 2,099 of 2,879 pairs (almost every qualifying pair, 100 of 829 race pairs) and never by more; there are no gaps. Four stints of `9574` end one lap after the driver's last lap.
- Timestamps come with and without microseconds, always with an offset.
- `meetings?year=Y` is the only source of a meeting's name, and its key has no cutoff, so for a season in progress it is fetched once and never again. OpenF1's 2026 calendar has changed since it started (Bahrain `1282` cancelled, `1308` added), so a stored copy goes stale. `meetings?year=2026&date_start<...` and `date_end<...` both filter correctly (curl, 2026-10-27).

## Options

Writing a session:

1. **Upsert per row** (`INSERT ... ON CONFLICT DO UPDATE`). Writes only what changed, but a row that disappears from the source stays, so the result depends on the history of runs.
2. **Replace per session**: delete the session's rows and load them again with `COPY`, in one transaction. The result depends only on the input; it rewrites a whole session (at most about 25,000 rows), which is cheap.

Keys:

1. **Generated ids** (`IDENTITY`). Every replace makes new ids, so the same input gives different rows, and anything that refers to a row (the assistant's citations, phase 6) breaks.
2. **Natural keys from the source.** Stable across runs; measured unique.

Knowing whether a session must be transformed again:

1. **Always transform.** Simple, but a season rerun rewrites everything.
2. **Skip when the input fingerprint and a hash of the transform's source files match the last success.** Automatic, but which files count is fuzzy, and a refactor that changes nothing recomputes everything.
3. **Skip when the input fingerprint and a `TRANSFORM_VERSION` constant match the last success, with a golden test that pins the version to the hash of the output of a fixed input.** A change to the output without a new version turns CI red.

Orchestration:

1. **A command that transforms and forgets.** No state between runs, no record of failures, and someone has to run it.
2. **Events: the ingest announces each completed session** (an external queue such as Redis Streams, NATS or Kafka, or `LISTEN/NOTIFY`) **to an always-on worker.** Lowest latency, but the ingest writes MongoDB and then publishes, which is not atomic: a crash between the two loses the event unless an outbox is added, and an always-on worker is a cost on free hosting tiers.
3. **A reconciling sweep over a run table in PostgreSQL**, run by the same scheduled job right after the ingest. The sweep derives what is pending from the raw store itself (a session whose raw data is complete and has no success for its current input and version), so it needs no event and repairs anything a previous run left undone. Sessions are claimed with `FOR UPDATE SKIP LOCKED`, so overlapping runs and several workers are safe. Latency is the schedule's period; with sessions settling 6 hours after they end (ADR 0006), an hourly schedule loses nothing that matters.

Bad data:

1. **Quarantine the bad rows and load the rest.** More data available, but a stint with missing laps calibrates the model wrong without saying so.
2. **Reject the session.** Nothing partial is ever loaded.

## Decision

Each session is transformed by a pure function of its raw documents into rows keyed by the source's natural keys, and written by replacing the session's rows with `COPY` in one transaction. The transform runs as a reconciling sweep after every ingest, in the same scheduled job, with no step done by hand: the sweep finds every session whose raw data is complete and whose input fingerprint or `TRANSFORM_VERSION` differs from its last success, workers claim them with `SKIP LOCKED`, transient errors are retried, and data the schema does not describe fails the session whole. Driver: psycopg 3. Migrations: Alembic, written by hand, applied by the deploy.

## Consequences

- No clock, random or generated id in the data. A row's identity is its natural key; `race_control`, which has none, is keyed by the session and the row's position in its raw response, stable because raw documents never change.
- Nullable columns are exactly the nulls measured; everything else is `NOT NULL`, with `CHECK` constraints on ranges, enum types for closed sets, and `UNIQUE` on every natural key. A value outside a closed set fails the session; adding it takes a migration.
- Gaps split into two typed columns: seconds as `NUMERIC`, laps behind as an integer. Qualifying times per phase go to their own table. Times are `NUMERIC`, never `float`.
- Consecutive stints may share one lap. That rule (the next stint starts on the previous one's last lap or the lap after) is checked in the domain; a database exclusion constraint would reject valid data.
- A stint ending one lap after the driver's last lap is accepted: it happens in the source and the transform does not correct it.
- Workers, attempts and backoff are configured (`TRANSFORM_MAX_CONCURRENCY`, `TRANSFORM_MAX_ATTEMPTS`, `TRANSFORM_BACKOFF_BASE_S`). Transient errors are lost connections, serialization failures and deadlocks; everything else is permanent and not retried.
- One entry point runs the whole refresh: ingest of the season in progress, telemetry of the latest Grand Prix, then the sweep. The scheduled job calls it; `make` targets are the same entry point for development, not a separate path.
- A worker holds its session's row lock for the whole transform and commits the clean rows and the success in the same transaction. If the process dies, PostgreSQL rolls the transaction back and releases the lock, the session is still pending, and the next sweep takes it. No lease, heartbeat or `running` status to clean up.
- A failure is recorded in its own transaction after the rollback. A failed session does not stop the others; the run exits non-zero so the scheduler marks it failed, and the run table keeps the error class and message with the raw document and row that caused it.
- Transient errors are retried within the run up to the limit, and again by the next sweep. A permanent error is not retried while the input and the version are the same: it waits for a code fix (a new version) or new raw data, so a broken session does not fail every hour.
- A session missing raw documents is `waiting_raw`, not failed. The sweep after the next ingest picks it up.
- Alerts read the run table (failed sessions, sessions waiting longer than a limit) and the exit code of the scheduled job; wiring them is phase 7.
- Migrations run in the deploy, before the new code serves traffic, never by hand. Because they never drop data in the step that adds its replacement (`AGENTS.md`), the old code keeps working while they run.
- Readers see a session only after its transaction commits, and only sessions that have been loaded once. A session that fails a later run keeps its previous good rows, and readers keep seeing them: the run table records the last load (`loaded_*`) apart from the status of the latest run.
- The run table stores the input fingerprint and a hash of the session's clean rows. The fingerprint covers the `_id` and `fetched_at` of the session's own documents and the content of its rows in the season index and the calendar, not those documents' identity: a season in progress stores a new index and calendar every hour, which would otherwise reload every session every hour. Determinism is proven by tests: two runs, one worker against several, in different orders, and a retry after a failure in the middle all give the same hash.
- The meetings request takes the same cutoff as the season index, on `date_start`: a qualifying settles before its meeting ends, and `date_end` would leave its meeting out until after the race. A season in progress gets a fresh calendar on each run; a finished season keeps one key. The meeting of a session is read from the meetings document of the same cutoff as the season index it came from. The `meetings?year=Y` documents stored before this change stay in the store and are not read.
- `adapters/migrate.py` and the `adapters/migrations` package that Alembic loads are the one adapter that imports Alembic and SQLAlchemy; Alembic connects through psycopg. All migrations run in one transaction behind an advisory lock, so two deploys that migrate at once queue instead of racing.
- Telemetry stays out of the clean model; phase 3 decides how it is replayed.
- An outbox for phase 3 (a session ready to replay) is not built here.
