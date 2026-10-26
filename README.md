# F1 Strategy Agent

[Español](README.es.md)

A Formula 1 platform being rebuilt in phases: a pipeline that ingests historical OpenF1 sessions and replays them as if live, a strategy simulator with a predictive tyre and lap-time model, and an assistant that answers with facts it retrieved and cites them. The plan, the standard the code follows and the current phase are in [AGENTS.md](AGENTS.md).

## What exists today

Phase 0, the foundation:

- **Backend** (`backend/`): Python 3.12, FastAPI, one endpoint, `GET /api/health`. Layered as domain, application and adapters; `import-linter` fails the build if an inner layer imports an outer one.
- **Frontend** (`frontend/`): React, Vite and TypeScript in strict mode. It shows the API status through a client generated from the backend's OpenAPI schema.
- **Infrastructure** (`infra/compose.yaml`): PostgreSQL with pgvector, MongoDB, the backend and the frontend. The databases run but nothing reads or writes them yet.
- **CI** (`.github/workflows/ci.yml`): the same checks as `make check` on every pull request, a check that the generated client matches the API, and a smoke test of the full stack.

Ingestion, the simulator and the assistant do not exist yet.

## Run it locally

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node.js 22 and GNU Make.

```sh
cp .env.example .env
make up
```

Open http://localhost:8080. `make down` stops the stack.

## Develop

```sh
make install   # backend and frontend dependencies
make check     # lint, format, types, layer rules, tests with coverage, build, API contract
make format    # apply the formatters
make openapi   # regenerate the frontend API client after changing an endpoint
```

## How it is built

Decisions are recorded in [docs/adr/](docs/adr/README.md). Each working session with the AI coding agent leaves an entry in [docs/devlog/](docs/devlog/README.md).
