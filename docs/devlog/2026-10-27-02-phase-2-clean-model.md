# 2026-10-27 · 02. Phase 2: clean model

**Goal:** turn the raw OpenF1 documents into a typed PostgreSQL model that loads deterministically, keeps its integrity and runs unattended in production.

## What happened

1. The author asked what came next. The agent read the repo: CI on `main` was green again after PR 5, so the next step was phase 2.
2. The author set the bar before any design: efficient reads and writes, idempotency, concurrency, error tracking, retry policies and data availability, with the alternatives and trade-offs of each. The reason, in the author's words (translated): "if something fails along the way and is retried, data risks being duplicated." The agent compared options per concern (trigger, write strategy, keys, driver, error handling) and recommended one each.
3. The author asked which options were deterministic and how integrity was ensured. The agent sorted each option by whether the final state depends only on the input, and changed two recommendations (see Corrections).
4. Mongo held only telemetry after the previous session's reset, so the agent ingested 2024 again (632 requests) and profiled every stored row before fixing a column or constraint: types, nulls, closed sets, uniqueness of each natural key, and cross-row rules.
5. The profile found that the calendar of a season in progress (`meetings?year=Y`) was stored once and never refreshed, while OpenF1's 2026 calendar had changed (Bahrain `1282` cancelled, `1308` added). Fixed first.
6. The agent drafted ADR 0008. The author pointed out that nobody runs commands by hand in production, and the design was reworked into a reconciling sweep run by the scheduled job.
7. Built in six steps, each verified and committed in layers: the meetings fix, migrations and the run table, the schema, the pure domain transform, the application sweep, then the adapters and the `transform` command.

## Decisions

- **Deterministic clean model, replaced per session in one transaction, natural keys, a reconciling sweep over a run table with `SKIP LOCKED`, transient-only retries, bad data fails its session alone**: [ADR 0008](../adr/0008-deterministic-clean-model.md).
- **The worker holds its session's row lock for the whole transaction**: a crash rolls back and frees the session, so there is no lease, heartbeat or `running` state to clean up.
- **The input fingerprint covers the session's own documents and the content of its index and calendar rows, not those documents' identity**: a season in progress stores a new index every hour, which would otherwise reload every session every hour.
- **`TRANSFORM_VERSION` is pinned by a golden test** on a trimmed real sample of the 2024 Bahrain race and qualifying, instead of a hash of the source files, where it is unclear which files count.
- **Calendar requests filter on `date_start<cutoff`**: a qualifying settles before its meeting ends, so `date_end` would hide the meeting until after the race.
- **`race_control` is keyed by its position in the raw document**: 85 instants in 2024 carry several messages. `pit_duration` is not stored; it equalled `lane_duration` in all 3472 stops, and a difference fails the session instead of dropping a value.
- **Every platform runs the selector event loop**, because the async PostgreSQL driver cannot run on Windows' default loop.

## Corrections and redirections

- The agent's ADR described the transform as a command. The author pointed out that production runs nothing by hand and that a scheduled job is planned (host not chosen yet). The transform became a sweep that starts after each ingest, recovers from a killed process without intervention, and leaves a run table that alerts can read.
- Asked what was deterministic, the agent replaced generated ids with the source's natural keys, so a reload keeps every row's identity, and replaced fail-fast with per-session isolation, so which sessions load does not depend on timing.
- The agent first proposed versioning the transform by a hash of its code, then switched to the golden test for the reason above.
- The agent first filtered the calendar on `date_end`, and corrected it to `date_start` before committing.
- ADR 0008 said readers see only sessions whose last run succeeded, and also that a failed rerun keeps the previous good rows. The agent fixed it to the second: the run table keeps the last load apart from the status of the latest run.
- A test caught a `CHECK` written with `=`, which a `NULL` let through; it now uses `IS NOT DISTINCT FROM`. `make migrate` ran the old image until it was given `--build`.

## Verification

- `make check`: exit 0. Backend 246 tests at 100% branch coverage; frontend 6 tests; contract check with no diff.
- All 60 sessions of 2024 through the domain transform: no error, the same hash on two runs, one clean row per raw row in every table.
- `make transform YEAR=2024` on the local stack: 60 loaded in 39 s (613,428 intervals, 38,005 laps, 77 MB). Rerun: 60 unchanged in 4 s.
- Clean model emptied, two transforms started at once: 32 and 28 loads, each session loaded once, no error; all 60 output hashes equal to the first load.
- A transform killed after 15 s: 21 sessions complete, 3 pending with no partial rows and no lock left. The next run loaded the other 39 with the same hashes.
- Sabotage: the migration lock, two schema rules, five domain guarantees and six sweep guarantees were each broken in turn; every break turned its named test red, and each was restored.
- CI on the branch: not run yet; it runs on the PR.

## Next

- Open the PR and check that CI starts the PostgreSQL test container on the runner.
- Phase 3, replay.
