# F1 Strategy Agent

[Español](README.es.md)

A Formula 1 platform being rebuilt in phases: a pipeline that ingests historical OpenF1 sessions and replays them as if live, a strategy simulator with a predictive tyre and lap-time model, and an assistant that answers with facts it retrieved and cites them. The plan, the standard the code follows and the current phase are in [AGENTS.md](AGENTS.md).

## What exists today

Phase 0, the foundation:

- **Backend** (`backend/`): Python 3.12, FastAPI, one endpoint, `GET /api/health`. Layered as domain, application and adapters; `import-linter` fails the build if an inner layer imports an outer one.
- **Frontend** (`frontend/`): React, Vite and TypeScript in strict mode. It shows the API status through a client generated from the backend's OpenAPI schema.
- **Infrastructure** (`infra/compose.yaml`): PostgreSQL with pgvector, MongoDB, the backend and the frontend. The databases run but nothing reads or writes them yet.
- **CI** (`.github/workflows/ci.yml`): the same checks as `make check` on every pull request, a check that the generated client matches the API, and a smoke test of the full stack.

Phase 1, ingestion:

- **Raw OpenF1 data in MongoDB**: every response of a season's Race and Qualifying sessions, one document per request, keyed by the endpoint and its parameters. A session is ingested once it ended at least `SESSION_SETTLE_H` hours ago (6 by default), so the season in progress works too: run it again after a race weekend and it adds only the new sessions. The client stays under OpenF1's free limit (3 requests per second, 30 per minute) and retries only errors that can succeed on retry.
- **Car telemetry** (`car_data`, `location`) for one session at a time, per driver in 30-minute windows. A whole season of it would not fit the free MongoDB tier ([ADR 0006](docs/adr/0006-raw-data-scope.md)).

The clean model, the replay, the simulator and the assistant do not exist yet.

## Run it locally

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node.js 22 and GNU Make.

```sh
cp .env.example .env
make up
```

Open http://localhost:8080. `make down` stops the stack.

Ingest raw data while the stack is up:

```sh
make ingest YEAR=2026              # settled Race and Qualifying sessions, about 20 minutes per full season
make ingest-telemetry SESSION=9472 # car_data and location of one session (2024 Bahrain race)
```

If a run fails, it exits with code 1 and one line naming the request that failed. Run the same command again: what was stored is skipped and the run continues from there.

## Develop

```sh
make install   # backend and frontend dependencies
make check     # lint, format, types, layer rules, tests with coverage, build, API contract
make format    # apply the formatters
make openapi   # regenerate the frontend API client after changing an endpoint
```

## How it is built

Decisions are recorded in [docs/adr/](docs/adr/README.md). Each working session with the AI coding agent leaves an entry in [docs/devlog/](docs/devlog/README.md).
