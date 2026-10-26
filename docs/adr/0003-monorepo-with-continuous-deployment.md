# 0003. Monorepo with continuous deployment to production

- Status: Accepted
- Date: 2026-10-26

## Context

The project has a backend (API, ingestion, replay, predictive engine, assistant), a frontend (simulator and chat) and infrastructure (databases, queue). It must reach production, and deploying must be simple enough that it happens on every merge, not as an occasional manual event.

## Options

1. **Monorepo.** Backend, frontend and infrastructure in one repository. One pull request can change an API field and the screen that shows it, and CI checks both together. One place for docs, ADRs and the devlog.
2. **One repository per part.** Independent histories and pipelines, at the cost of coordinated releases and contracts that drift between repositories.

## Decision

Option 1, with these rules:

- Top-level directories per deployable part (backend, frontend) plus one for infrastructure. Phase 0 creates them and records them in `AGENTS.md`.
- Every service runs in a container. The same images run locally (compose) and in production.
- One command runs the whole stack locally, and one command (`make check`) runs every check CI runs.
- CI runs on every pull request, with path filters so a frontend-only change does not rebuild the backend.
- A merge to `main` that passes CI deploys to production automatically. Database migrations run as a release step before the new version takes traffic.
- Configuration comes only from environment variables; secrets come from the host's secret store.

## Consequences

- No manual deploy step exists, so anything a deploy needs lives in the repository.
- `main` must always be deployable: work happens on branches and merges only when green.
- The hosting provider is chosen in its own ADR when the first service is deployable; this decision does not depend on it.
