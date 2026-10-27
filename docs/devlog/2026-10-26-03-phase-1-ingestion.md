# 2026-10-26 · 03. Phase 1: ingestion

**Goal:** ingest raw OpenF1 data into MongoDB within the free rate limit, idempotent by request, and measure one season against the free tier.

## What happened

1. The session opened from the previous entry's Next. Before planning, the agent measured the real API with curl on the 2024 Bahrain race: per-endpoint sizes, `car_data` and `location` rejected for a whole session (422), and empty results answered as 404 "No results found.".
2. The agent proposed the plan and asked three scope questions. The author chose telemetry for one demo session, Race and Qualifying by default, and asked how a failed run is reported and retried before choosing how ingestion is triggered.
3. The agent answered: transient errors are retried with backoff inside the run, anything else stops it with exit code 1 and one line naming the request, and a rerun resumes because every response is stored once under its key. The author approved a CLI behind `make ingest`.
4. The agent posted the owner check and evidence, then built the domain (endpoints, request keys, request plans), the use cases, and the adapters (settings, rate limiter, OpenF1 client, Mongo raw store, CLI), with tests against a real Mongo container.
5. The agent ingested 2024 for real from wiped volumes, reran it, ingested the Bahrain telemetry, and recorded the scope and sizes in [ADR 0006](../adr/0006-raw-data-scope.md).
6. The author asked how this runs and stays current in production, then decided the season in progress belongs in this phase. The agent read OpenF1's data-availability notes, replaced the finished-season rule with a settle time, and ingested 2026 up to the race of the day before.

## Decisions

- **Raw data scope**: settled Race and Qualifying sessions by season, telemetry per session in 30-minute windows. [ADR 0006](../adr/0006-raw-data-scope.md).
- **Settled sessions, season in progress included**: a session is ingested once it ended `SESSION_SETTLE_H` hours ago (6 by default). The season index carries a cutoff truncated to the hour, so a settled season always has the same key and a season in progress gets a new index on each run.
- **The request key is the query sent**: the document `_id` is the endpoint plus the sorted query in OpenF1's own syntax, so MongoDB's built-in unique index enforces one write per request.
- **httpx2 instead of httpx**: it was already in the lockfile through the test client, so the project keeps one HTTP library.
- **LF everywhere**: `.gitattributes` forces LF on checkout.

## Corrections and redirections

- The author asked how a failed run would be noticed and retried before choosing the trigger. That made the failure behavior (exit code, one-line error, resume on rerun) part of the plan instead of an implementation detail.
- The agent limited ingestion to finished seasons, so a stored season index could not freeze future sessions as missing. After grading, the author asked how the command runs in production and how the data stays current; the answer exposed that 2026 could not be ingested until January. The agent proposed a separate PR; the author first agreed, then reversed it: (translated) "only finished seasons makes no sense; what if I want to ask about this week's race?". The settle-time design went into this PR, and the 48-hour margin first proposed became 6 hours after reading OpenF1's notes on when data turns historical.
- The agent changed course on its own in these places:
  - The first telemetry design sent date filters as encoded key-value pairs. Checked against the API during review, that form returns 500 (OpenF1 decodes the whole query before reading operators). The domain now writes `date>=value`.
  - `make ingest` ran the image built at `make up`, so a code change would not reach it; it now runs with `--build`.
  - The CLI compared subcommand names as strings; each subcommand now registers its handler.
  - `make check` failed on this machine before any change: CRLF working copies broke Prettier and the OpenAPI contract check, and `print()` wrote the schema with CRLF. Fixed with `.gitattributes` and a generator that writes bytes.

## Verification

- `make check`: exit 0. Backend 90 tests at 100% branch coverage; import-linter "1 kept"; frontend 6 tests; contract check with no diff.
- Sabotage: nine breaks (unsorted keys, any 404 as empty, 422 retried, overwrite on rewrite, no concurrency bound, cancelled sessions kept, limiter off by one, rerun refetching, `key=value` comparison syntax), each turned its named tests red; all restored.
- Reset: `docker compose down -v`, `make up`, `make ingest YEAR=2024`: 60 sessions, 632 requests, 21 minutes, exit 0; 123.6 MB of data, 23.6 MB of storage, largest document 4.6 MB.
- Rerun: 632 requests, 0 fetched, 8 seconds.
- `make ingest-telemetry SESSION=9472`: 162 requests, 5 minutes, 0 empty windows, 135.6 MB; rerun fetched 0.
- `make ingest YEAR=2026` (season in progress): 48 sessions, 506 requests, 17 minutes, exit 0; the results of the race of 2026-10-25 (`11396`) were stored. A rerun in the same hour fetched 0; rerunning 2024 fetched only its new index.
- Sabotage of the settle logic: no domain cutoff filter, no hour truncation, no season-end cap, telemetry ignoring the settle time; each turned its named tests red; all restored.
- CI: not run in the session; it runs on the PR.

## Next

- Phase 2, clean model: the PostgreSQL schema per season and the transform from the raw documents, starting with sessions, drivers, laps and stints.
