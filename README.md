# F1 Strategy Agent

[Español](README.es.md)

A Formula 1 platform being rebuilt in phases: a pipeline that ingests historical OpenF1 sessions and replays them as if live, a strategy simulator with a predictive tyre and lap-time model, and an assistant that answers with facts it retrieved and cites them. The plan, the standard the code follows and the current phase are in [AGENTS.md](AGENTS.md).

## What exists today

Phase 0, the foundation:

- **Backend** (`backend/`): Python 3.12, FastAPI, one endpoint, `GET /api/health`. Layered as domain, application and adapters; `import-linter` fails the build if an inner layer imports an outer one.
- **Frontend** (`frontend/`): React, Vite and TypeScript in strict mode. It shows the API status through a client generated from the backend's OpenAPI schema.
- **Infrastructure** (`infra/compose.yaml`): PostgreSQL with pgvector, MongoDB, Redis, the backend and the frontend.
- **CI** (`.github/workflows/ci.yml`): the same checks as `make check` on every pull request, a check that the generated client matches the API, mutation testing of the domain, and a smoke test of the full stack. `main` takes changes only through a pull request with these checks green; the owner can merge past a red one (ADR 0010).

Phase 1, ingestion:

- **Raw OpenF1 data in MongoDB**: every response of a season's Race and Qualifying sessions, one document per request, keyed by the endpoint and its parameters. A session is ingested once it ended at least `SESSION_SETTLE_H` hours ago (6 by default), so the season in progress works too: run it again after a race weekend and it adds only the new sessions. The client stays under OpenF1's free limit (3 requests per second, 30 per minute) and retries only errors that can succeed on retry.
- **Car telemetry** (`car_data`, `location`) of the latest settled Grand Prix, per driver in 30-minute windows. Only one session of telemetry is kept: when a new one is fully stored, the previous one is deleted, because each race weighs about 150 MB and the free MongoDB tier is 512 MB ([ADR 0007](docs/adr/0007-telemetry-of-the-latest-grand-prix.md)).

Phase 2, the clean model:

- **Typed tables in PostgreSQL** for every ingested session: meetings, sessions, drivers per session, laps, stints, pits, intervals, positions, race control, weather, results, qualifying phases, starting grid, overtakes and team radio. Times and gaps are exact numbers, a gap of "+1 LAP" is a lap count, closed sets are enums, and constraints reject what the 2024 season did not show ([ADR 0008](docs/adr/0008-deterministic-clean-model.md)).
- **A deterministic load**: the same raw data gives the same rows, whatever the order, the number of workers or a crash in the middle. Each session is replaced whole in one transaction, a rerun loads only what changed, and a session with bad data fails alone with the document and row that caused it.

Phase 3, the replay:

- **A replay API** over any session in the clean model: `POST /api/replays` starts one at 1x to 60x, `/pause`, `/resume` and `/speed` control it, `/seek` moves it to the earliest start of a lap ([ADR 0012](docs/adr/0012-seek-to-a-lap.md)), `DELETE /api/replays/{id}` stops it and frees its place ([ADR 0011](docs/adr/0011-a-viewer-stops-their-replay.md)), and `GET /api/replays/{id}/events` streams its laps, positions, intervals, pits, race control, weather, overtakes and team radio over Server-Sent Events, in the order and at the pace they happened. A viewer that reconnects resumes after its last event; after a seek the stream starts again with a reset, then what is still current at that lap (each driver's latest position, interval and lap, the latest weather, and every pit, race control message, overtake and team radio), so a late lap shows in under a second ([ADR 0013](docs/adr/0013-a-seek-sends-what-is-still-current.md)). The events go through a Redis stream per replay; the same session always gives the same stream ([ADR 0009](docs/adr/0009-replay-from-the-clean-model.md)).
- **The loaded sessions**: `GET /api/sessions` lists every session in the clean model with its meeting, the latest first, and `GET /api/sessions/{session_key}` adds its drivers with their team and colour, and its last lap number.
- **The replay screen** at http://localhost:8080: pick a Grand Prix, one of its sessions and a speed, and watch it as it happened: the leader's lap and the latest flag for the whole track, the timing tower (position, interval or gap to the leader, last lap, tyre and its age, last stop), the last lap of the driver you follow with its sectors and speed traps, the weather and race control. Pause, resume and change the speed while it plays, or type a lap and go to it: the screen rebuilds as it was at that lap's start and plays on; choosing another session stops the replay you leave. The circuit map and the strategy tools have their place on the screen but are not built yet. Every number on the screen came in an event: the screen keeps the latest value of each, and every race control message.

The simulator and the assistant do not exist yet.

## Run it locally

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node.js 22 and GNU Make.

```sh
cp .env.example .env
make up
```

Open http://localhost:8080; the replay screen lists the sessions loaded with `make transform` (below). `make down` stops the stack. `make up` also brings the PostgreSQL schema to the latest migration; `make migrate` does only that. A `.env` copied before phase 2 needs the new `POSTGRES_CONNECT_TIMEOUT_S` and `TRANSFORM_*` lines from `.env.example`, and one copied before phase 3 the `POSTGRES_POOL_SIZE`, `REDIS_*` and `REPLAY_*` lines, `REPLAY_APPEND_BATCH` included.

Ingest raw data while the stack is up:

```sh
make ingest YEAR=2026              # settled Race and Qualifying sessions, about 20 minutes per full season
make ingest-telemetry              # car_data and location of the latest settled Grand Prix
make ingest-telemetry SESSION=9472 # or of another session (2024 Bahrain race); either replaces the stored telemetry
```

If a run fails, it exits with code 1 and one line naming the request that failed. Run the same command again: what was stored is skipped and the run continues from there.

Load an ingested season into the clean PostgreSQL model:

```sh
make transform YEAR=2026 # every ingested session that changed since its last load, in about a minute per season
```

A session whose raw data is still incomplete waits for the next run; a session whose data the schema does not describe fails alone, with one line naming the document and the row, and the run exits with code 1. Running it again loads only what changed (ADR 0008).

## Develop

```sh
make install    # backend and frontend dependencies
make check      # lint, format, types, layer rules, tests with coverage, build, API contract
make fast-check # the static half of make check, in about a minute; Claude Code runs it before a commit
make mutation   # mutation testing of the domain in a Linux container; fails if a mutant survives
make format     # apply the formatters
make openapi    # regenerate the frontend API client after changing an endpoint
```

## How it is built

Decisions are recorded in [docs/adr/](docs/adr/README.md). Each working session with the AI coding agent leaves an entry in [docs/devlog/](docs/devlog/README.md).
