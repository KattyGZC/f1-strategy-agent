# 2026-10-26 · 01. Audit of the first MVP and agent setup

**Goal:** decide what to keep from the February MVP, fix the direction of the rebuild, and give the agent the rules, skills and log it will work with from now on.

## What happened

1. The author shared the new project brief: a data pipeline (raw events in a NoSQL store, async cleaning into a query-optimized database), an interactive strategy simulator with a predictive engine for tyre degradation and lap times, and an assistant with RAG over a vector database. The brief stresses clean architecture, async concurrency, justified technology choices, local-first execution and production readiness.
2. The agent audited the whole repository (56 tracked files, about 1,300 lines of Python, 8 commits from February 2026) and compared it with the brief.
3. The author settled three open questions (see Decisions).
4. The agent reviewed the author's personal rule sets and the standards of two earlier projects, and adapted what applies here into `AGENTS.md` and three skills. Everything employer-specific was left out.
5. The agent created the ADR folder with the three decisions, and this devlog.

## Audit summary

What exists: a synchronous OpenF1 ingestion of sessions, drivers, laps and intervals into PostgreSQL with raw JSON copied to LocalStack S3; a read-only FastAPI; race summaries written by a local 3B model, embedded with pgvector; a two-node LangGraph agent (retrieve, generate) that no endpoint exposes. No tests, no linting, no CI.

Findings that decided a rewrite over a refactor:

- The README promised streaming, multi-tool orchestration, FIA regulation search and real-time analysis. None of it existed.
- `drivers` was keyed by `driver_number` alone, and each upsert overwrote the team, so every past race showed the latest team.
- The assistant indexed summaries the model wrote from data that had no finishing positions or tyre compounds, so it could not answer "who won" without inventing it.
- `stint` was always null and compounds were never ingested, which blocks any degradation model.
- Gaps were stored as strings (`"+1 LAP"` mixed with seconds).
- No async I/O anywhere, the domain imported infrastructure directly, no foreign keys, naive timestamps, no vector index.
- The OpenF1 client waited 0.35 s between requests. The free tier allows 30 requests per minute (openf1.org, read today), so a full season would hit rate limits.

Kept as ideas: separating raw from clean data, validating raw responses before mapping, retry with backoff, PostgreSQL with pgvector in Docker, upserts with `ON CONFLICT`.

## Decisions

- **Replay instead of the live feed**: live OpenF1 data is paid and only exists during sessions; replay is free, available any day and deterministic. [ADR 0001](../adr/0001-replay-instead-of-live-feed.md).
- **pgvector**: one engine less, and vectors sit next to the rows they describe. [ADR 0002](../adr/0002-pgvector-as-vector-store.md).
- **Monorepo with continuous deployment**: the project must reach production, and deploying must be simple enough to happen on every merge. [ADR 0003](../adr/0003-monorepo-with-continuous-deployment.md).
- **Devlog and ADRs are public and in English**, because they are part of what the project demonstrates.
- **Rules target Claude Code only** (`AGENTS.md`, `CLAUDE.md`, `.claude/skills/`).

## Corrections and redirections

- The agent recommended a monorepo with the frontend deferred until the simulator works. The author agreed on the monorepo and added a requirement the agent had not raised: the project must reach production, with continuous deployment and a simple deploy. That became ADR 0003.
- The author invited questions to refine the setup before it was written. The agent asked four (log language, log depth, public ADRs, which tools the rules target) and wrote nothing until they were answered; the author took the recommended option on all four.

## Verification

- OpenF1 pricing and rate limits: read from openf1.org during the session (quoted in ADR 0001).
- `make check`, tests and linting: do not exist yet; phase 0 creates them.

## Next

- Phase 0: monorepo layout, tooling, `make check`, CI, containers. Start by choosing the NoSQL store and the frontend stack in the session, recording each as an ADR.
- Rewrite the README so it describes only what exists.
