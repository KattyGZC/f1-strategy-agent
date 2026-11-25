# 2026-11-25 · 01. Phase 6: the answer's contract and the tool loop

**Goal:** build T1 of the phase 6 plan: the answer's events and the bounded tool loop, tested against a scripted fake model.

## What happened

The author asked for the next step, then for T1 with the skills that fit the task, including the external collection's. The agent used test-driven-development and incremental-implementation from it, with the project's self-grade and tech-audit. It wrote the owner check and the evidence, then each layer test first: the domain's closed sets, events and citation ledger, then the use case against a scripted fake model and fake tools. Sabotage on the round counter and the citation numbering turned the expected tests red, and the files were restored from a copy.

## Decisions

- Tool inputs are validated by each tool's adapter, which answers `Rejected`. import-linter forbids Pydantic in the application layer, so the loop never sees it. ADR 0021's "validate with the tool's Pydantic model" still holds, one layer out.
- `decline_question` is a port of its own (`DeclineTool`) and emits no step. Its result is `Declined` or `Rejected`, so a data tool cannot decline by type.
- The answer runs as a task raced against a passed-in timer. A stalled model call is cancelled at the answer's timeout and ends with `answer_timeout`. Before, it could have waited for the SDK's own timeout.
- A stop reason the loop does not handle, a tool that was not offered, and a tool error other than `ToolFailedError` raise. The route (T3) turns them into `internal_error` and logs them with the request id.

## Corrections and redirections

- The plan listed the `row`, `article` and `simulation` sources for T1. The agent defined only `row`, because the other two would need fields that T6 and T11 build. The plan was amended in the same pull request.

## Verification

- `make check`: exit 0, 731 backend tests and 188 frontend tests passed, total coverage 100.00%.
- `make mutation`: exit 0, 2422 mutants, none survived (2 timeouts in `domain/openf1.py`, which count as caught).
- `make fast-check`: exit 0 before each commit (hooks).
- No live call; no credits spent.

## Next

- T2, T3 or T4: each depends only on T1. T4 carries the highest provider risk, and recording its responses spends cents (ask first).
