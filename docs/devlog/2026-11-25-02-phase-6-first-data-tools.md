# 2026-11-25 · 02. Phase 6: the first data tools

**Goal:** build T2 of the phase 6 plan: `find_races`, `race_results` and `driver_strategy` over the clean model.

## What happened

After T1 merged, the session built T2 test first against PostgreSQL in a container, with the real 2024 Bahrain sample. The reads live in the clean store, the only importer of psycopg, each in one read-only snapshot. The tools validate the model's input with Pydantic, cap their results and turn each row into a citable source with the driver's name and team. Sabotage dropped `READ ONLY` and reversed the classification's order; the exact tests turned red each time. The first try at the second sabotage did not apply (a wrong pattern) and was redone.

## Decisions

- `find_races` returns citable `session` rows: [ADR 0025](../adr/0025-find-races-returns-citable-session-rows.md), which supersedes ADR 0023's list of row tables.
- `Found` counts the rows past the cap (`omitted_rows`); the words that tell the model belong to the Anthropic adapter (T4).
- Only an unreachable store fails a tool (`OperationalError` becomes `ToolFailedError`); any other database error, a refused write included, fails the answer.
- An unknown `session_key` or a driver who did not take part is `Rejected`; a driver without stints or stops is `Empty`.

## Corrections and redirections

- ADR 0021 asks every data tool for citable blocks, while ADR 0023's row tables had no value for a race. The agent asked; the author chose adding `session` over returning `find_races` as plain text.

## Verification

- `make check`: exit 0, 758 backend tests and 188 frontend tests passed, total coverage 100.00%.
- `make mutation`: exit 0, 2425 mutants, none survived.
- No live call; no credits spent.

## Next

- T3 (settings and the HTTP contract) or T4 (the Anthropic adapter, whose recordings spend cents: ask first).
