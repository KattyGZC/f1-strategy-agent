# 2026-10-27 · 01. Telemetry of the latest Grand Prix

**Goal:** make the telemetry ingestion follow the latest settled Grand Prix instead of a session picked by hand, and keep MongoDB within the free tier.

## What happened

1. The session opened with a reference diagram of a generic F1 RAG pipeline. The agent mapped it to the project: phase 1 covers the raw side of ingestion; regulations ingestion, the clean model, the vector store and the assistant do not exist yet; Kafka, a lakehouse and a hosted vector database are replaced on purpose (ADRs 0001, 0002, 0004).
2. The author pointed out that the stored telemetry (2024 Bahrain, chosen in phase 1 to measure sizes) should be the latest session instead. The agent offered two paths: ingest the latest session by hand, or make the latest Grand Prix the default and keep one session of telemetry. The author chose the second, for the latest race only.
3. Before coding, the agent checked OpenF1 with curl: one request filtered by `session_name=Race` lists every Grand Prix without sprints, three of them cancelled.
4. The agent built the domain rule, the use case, the delete in the Mongo store with an index, and the optional CLI argument, then ran the real command against the stored data: it picked `11396` and replaced the Bahrain telemetry.

## Decisions

- **Latest settled Grand Prix by default, telemetry of one session kept**: [ADR 0007](../adr/0007-telemetry-of-the-latest-grand-prix.md), which replaces the telemetry part of ADR 0006.
- **Sprints excluded**: "the latest race" is the Grand Prix; filtered by OpenF1's `session_name`, verified with curl.
- **Delete after store**: the previous session's telemetry goes only once the new one is complete, so a failed run never leaves the store without telemetry.

## Corrections and redirections

- The agent proposed a "latest session" default without saying which session types count. The author narrowed it to the latest race, which keeps storage at one race (about 150 MB) instead of two.
- The agent renamed the use case during grading (`IngestLatestRaceTelemetry` to `IngestLatestGrandPrixTelemetry`) so the code and the ADR use one name, and corrected the size in the ADR from 135 MB (20 drivers in 2024) to the 153 MB measured on a 22-driver race.
- The permission system refused the agent's volume wipe for the reset check; the author ran it.

## Verification

- `make check`: exit 0. Backend 105 tests at 100% branch coverage; frontend 6 tests; contract check with no diff.
- Sabotage: eight breaks (cancelled race kept, no tie-break, cutoff inclusive, no `session_name` filter, no delete, delete before fetch, delete of other endpoints, delete of the kept session), each turned its named test red; all restored.
- `make ingest-telemetry` with `9472` stored: chose `11396`, 178 requests in 5 min 19 s, 176 telemetry documents (153.3 MB), 160 deleted. A rerun fetched and deleted nothing.
- Reset (`down -v`, `make up`, `make ingest-telemetry`): run by the author from wiped volumes; the store then held 178 documents: 176 telemetry documents of `11396` (153.3 MB), the Grand Prix index and the driver list.
- CI: the `backend` job of `main` fails since the PR 3 merge, on the 14 tests that start Mongo with testcontainers, on runner image `ubuntu-24.04 20261025.353.1`; it passed on `20261012.334.1` with the same tree. Not fixed in this PR.

## Next

- Fix the CI failure on its own branch, starting by printing the Mongo container's logs in CI.
- Phase 2, clean model.
