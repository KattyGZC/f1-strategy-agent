# 2026-10-29 · 01. Phase 3: replay API

**Goal:** replay a stored session as if live, from the clean model through Redis Streams to the browser over SSE, deterministic whatever the pace.

## What happened

1. The author asked for the state of the project and what came next. `main` was clean and CI green after PR 6, so the next step was phase 3.
2. The agent proposed three decisions with a recommendation each: the source (clean model, telemetry out), the queue (Redis Streams) and the transport (SSE). The author took the first two and asked for the third to be explained; then asked whether the plan was really to play a whole race (translated). The agent described what a replay is and what it is for (ADR 0001), and the author confirmed the phase.
3. Before the ADR the agent measured the 2024 Bahrain race and season in the clean model: events per table, how to place a lap in time, laps without a duration or a stint, repeated instants. The author chose one replay per viewer, the producer inside the backend, and seek as the last step of the phase.
4. Built in three steps, each self-graded, audited and committed by layer: the pure timeline, the pacing and the use cases, then the adapters (PostgreSQL reader, Redis store, wire events, REST and SSE routes, compose).
5. The author asked whether the frontend belonged in this branch. The agent recommended one concern per PR: this branch ships the replay API; the replay screen and seek follow in their own PRs.

## Decisions

- **Replay from the clean model, Redis Streams per replay, SSE with REST controls, one replay per viewer, producer in the backend process, telemetry not replayed**: [ADR 0009](../adr/0009-replay-from-the-clean-model.md).
- **A lap happens when it ends** (`date_start + lap_duration`, which matched the next lap's start within 0.5 s in 28,360 of 28,416 race pairs); a lap without either is counted, not placed by guessing.
- **Pacing is pure and decides by wall instants**, the same ones the producer waits for, so float rounding cannot leave an event whose wait is over unsent.
- **The limit on active replays is enforced by the store** when it creates one, so the check and the insert cannot race.
- **The SSE route is annotated with the event models** so their schemas reach the generated TypeScript client; a route that only yields `ServerSentEvent` (which carries the id) leaves them out of OpenAPI.

## Corrections and redirections

- The agent planned Redis and its settings as the first step. Before writing it, it saw nothing would read them until the adapters, and built the pure domain first.
- The first pacing compared session times while the producer waited on wall times; a rounding gap could have looped forever. Caught on review, before any test ran.
- A docstring claimed every replayed number has at most three decimals. Measured: intervals carry up to 15. All 1,342,061 replayed numbers of 2024 round-trip exactly through a double, which is what the docstring now says.
- The fake clock in the tests never yielded to the event loop, so cancellation and shutdown tests proved nothing. Fixed before trusting them.
- A Redis client built on an explicit pool did not close it; tests caught the leaked sockets (`Redis.from_pool`).
- Timing the stream with the project's HTTP client showed a 21 s delay. `curl` showed the first byte at 0.25 s: the delay was the client's buffering, not the server.

## Verification

- `make check`: exit 0. Backend 372 tests at 100% branch coverage; adapters against real PostgreSQL and Redis containers.
- Sabotage: 34 guarantees across the timeline, pacing, use cases, reader, store and routes, each broken in turn; every one turned its named test red and was restored.
- `make up` and a full replay of the 2024 Bahrain race at 60x: all 32,493 events, ids `0-1` to `0-32493`; 1,750 s of session in 28.9 s of wall time, each event between 0 and 0.3 s ahead of its schedule; the same through nginx. One replay holds 6.2 MB in Redis.
- One `make check` failed in the teardown of the PostgreSQL test container (Docker Desktop's named pipe closed, error 109) after every test had passed; the next runs passed. Not fixed; it is the Windows Docker host.
- CI on the branch: not run yet; it runs on the PR, with the first Redis test container on the runner.

## Next

- Open the PR and check that CI starts the Redis container.
- The replay screen: an endpoint listing loaded sessions with their drivers, the timing tower and the controls.
