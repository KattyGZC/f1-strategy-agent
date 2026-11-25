# 2026-11-25 · 03. Phase 6: the assistant's HTTP contract

**Goal:** build T3 of the phase 6 plan: the assistant's status, its streamed answers and the settings they read.

## What happened

The session built `GET /api/assistant` and `POST /api/answers` test first, with T1's scripted fake model behind a real API over PostgreSQL and Redis. The four suggestions come from the spec's examples, checked against the local stack's clean model (Monza 2024 is 9590, where Norris ran three stints; Silverstone 2024 is 9558); the golden questions check them again in T15. Sabotage on the stream's cancel and on the failure handling made the tests hang instead of fail; the cancel test gained a 5 s bound, so it now fails.

## Decisions

- The stream ends with `done` or `error` once it started: a failure inside the answer is logged as `answer_failed` and sent as `internal_error`, and the request's log line carries the code.
- The question's length limit is a setting, so the route checks it and answers the same 422 `invalid_request`, without the question's text.
- T3 reads two settings, `ASSISTANT_ENABLED` and `ASSISTANT_QUESTION_MAX_CHARS`. The keys, the model's settings, the answer's limits and the SDK-timeout check move to T4, and the budget's to T12, where something reads them. Until T4 an enabled assistant refuses to start and names the missing adapter.
- `decline_question` offers a suggestion by its id, from a closed set.

## Verification

- `make check`: exit 0, 778 backend tests and 188 frontend tests passed, total coverage 100.00%.
- `make mutation`: exit 0, 2425 mutants, none survived.
- No live call; no credits spent.

## Next

- T4, the Anthropic adapter: recording its responses spends cents and needs an API key in `.env` (ask first).
