# Plan: Phase 6, the assistant (V1)

- Status: draft, 2026-11-23
- Source: [the phase 6 spec](phase-6-assistant.md) and [ADR 0021](../adr/0021-the-assistant-is-a-bounded-tool-loop-behind-one-port.md) to [ADR 0024](../adr/0024-regulations-by-edition-embedded-in-pgvector.md), which bind where this plan differs.
- Each task is one pull request, planned again in the session that starts it (owner check, evidence). A box is ticked in the pull request that closes it.

## Overview

The phase is cut into vertical slices. The first one answers a fact question end to end, from the tab to the model and back, so the riskiest pieces (the tool loop, the provider's streamed citations, the SSE route) meet early. Each later slice adds one kind of question or one guarantee: what if, rules, limits and budget, refusals and the paused state. The golden questions close the phase.

## Dependency graph

```
T1 contract and loop ── T2 first data tools
T1 ── T3 HTTP and settings
T1 ── T4 Anthropic adapter
T3 + T4 ── T5 the tab ── checkpoint A
T2 + T5 ── T6 what-if and the remaining data tools

T7 manifest and ingest-rules ── T8 splitter ── T9 rule store and embed sweep ── T10 Voyage adapter
T5 + T10 ── T11 search_rules ── checkpoint B

T3 + T4 ── T12 budget and concurrency ── T13 edge and the answer log
T5 + T12 ── T14 refusals and the paused state ── checkpoint C

T1 to T14 ── T15 golden questions and the eval ── T16 close the phase
```

T7 to T10 depend on no other task and can run in parallel with slice A and B.

## Tasks

### Slice A: a fact question, end to end

#### T1. The answer's contract and the tool loop

- [x] `domain/assistant.py`: the closed sets `ToolName`, `AnswerEventKind`, `StepStatus`, `DeclineReason`, the answer outcomes and error codes, the `row` source and the answer events, as frozen dataclasses (ADR 0023), and the ledger that numbers citations. The `article` source joins in T11 and the `simulation` source in T6, where their fields are built and tested.
- [x] `application/assistant.py`: the `LanguageModel` and tool ports and the bounded loop of ADR 0021, against a scripted fake model. Limits come in as values: tool rounds, output tokens per turn (a `max_tokens` stop), the answer's timeout through a passed-in timer. Tool inputs are validated by each tool's adapter, which answers `Rejected`; the loop never imports Pydantic.
- [x] Tests: an answer that ends, each limit reached with its code, an invalid tool input (`rejected`, counts as a round), a failing tool (`failed`), an empty result (`empty`), `decline_question`, a citation outside the ledger dropped, a stop reason the loop does not know.

Verification: `make check`, `make mutation` (no surviving domain mutant). Files: 2 source, 2 test. Size M. Depends on nothing.

#### T2. The first data tools: `find_races`, `race_results`, `driver_strategy`

- [ ] One Pydantic input model per tool; its JSON schema is the tool's `input_schema`.
- [ ] Our own queries in a `READ ONLY` transaction; a `session_key` the clean model lacks is an error result; results capped by `ASSISTANT_TOOL_MAX_ROWS` with a truncation notice.
- [ ] Each row becomes a `row` source with its key (`row:<table>:<session_key>:<key...>`).
- [ ] Testcontainers tests on a synthetic race, including a write attempted inside the read-only transaction being refused.

Verification: `make check`. Files: a new `adapters/assistant_tools.py` (name fixed when the task starts), its test. Size M. Depends on T1.

#### T3. Settings and the HTTP contract

- [ ] Settings: `ASSISTANT_ENABLED` (required), the limits and prices of ADR 0022, the keys as `SecretStr` required only when enabled; `.env.example` lists them. The settings refuse an SDK timeout that is not below the answer's (ADR 0021).
- [ ] `ErrorCode` gains the assistant's codes (ADR 0023).
- [ ] `GET /api/assistant` (`available` or `disabled`, the 4 to 6 suggestions defined in the backend) and `POST /api/answers` as SSE of typed events, the task cancelled when the browser disconnects.
- [ ] Route tests with the fake model: event order, the errors before the stream, 503 `assistant_disabled`, the request id; `make openapi` regenerates the client.

Verification: `make check` with no credentials. Files: `adapters/settings.py`, `adapters/http/errors.py`, `adapters/http/assistant.py`, `adapters/http/services.py`, tests. Size M. Depends on T1.

#### T4. The Anthropic adapter

- [ ] Add `anthropic` (approved in ADR 0021); `adapters/language_model.py` is its only importer, with an import-linter contract.
- [ ] Map a streamed turn to the port's events: text deltas, `citations_delta` with `search_result_location`, tool calls, the stop reason and the usage (input, cache write, cache read, output).
- [ ] Tool results as `search_result` blocks with citations on; `cache_control` on tools, system and the last input block; the model, `max_tokens`, retries and timeout from settings.
- [ ] Errors: the spend limit (both documented shapes), overloaded or failing after retries (`model_unavailable`), `refusal` (`model_refused`), any other 400 (`internal_error`). Unknown event types ignored.
- [ ] Tests against recorded responses. **Ask first:** recording them is one short live session that spends a few cents.

Verification: `make check` with no credentials. Files: `adapters/language_model.py`, the recordings under `tests/fixtures/`, its test, `pyproject.toml`, `uv.lock`. Size M. Depends on T1. Highest provider risk: if the citations do not arrive as ADR 0021 quotes, ADR 0021 is revisited here, before the tab relies on them.

#### T5. The Assistant tab

- [ ] A tab in the URL (ADR 0018): the suggestions, a question box with its length limit, the steps as they arrive, the prose rendered as paragraphs, bullets and bold by our own parser, never HTML (ADR 0022).
- [ ] Citation markers open a panel that shows a `row` source; an `error` event shows its message; one line says the question is sent to the providers and stored nowhere.
- [ ] Vitest: streaming text, steps, citations, each error code, text that looks like HTML or a link staying plain.

Verification: `make check`. Files: `frontend/src/assistant/` (3 to 5 files), `ScreenTabs.tsx`, `screens.ts`. Size M. Depends on T3 (generated types) and T4 (the event shapes it renders).

**Checkpoint A.** `make check` exits 0. With the stack up and a key set, a fact question about a 2024 race is answered in the tab with its steps and a citation that opens its row. **Ask first:** this spends cents. Review with the author.

### Slice B: what if, and the rest of the data

#### T6. `lap_times`, `race_control`, `weather`, `simulate_strategies`

- [ ] The three row tools with their bounds (lap range, category, readings every 10 minutes, at most 30).
- [ ] `simulate_strategies` calls the phase 5 use case with the body of `POST /api/simulations`, and returns one `simulation` source; the panel shows it.
- [ ] Tests as in T2, and a simulation the race cannot run coming back as the simulator's own rejection.

Verification: `make check`. Files: the tools module, its test, the panel. Size M. Depends on T2 and T5.

### Slice C: the regulations

#### T7. The manifest and `make ingest-rules`

- [ ] Before the code: extract the text of one 2024 and one 2026 edition with `pypdf` locally, not committed, and confirm the two numbering formats of ADR 0024.
- [ ] `adapters/rules_manifest.json`: every edition in force at a race of the clean model, with URL, date, issue, revision and SHA-256, written by hand from the FIA's listing.
- [ ] `make ingest-rules YEAR=...` downloads what the raw store lacks, checks the hash (a mismatch fails the run and names the edition) and stores the bytes, one document per edition.
- [ ] Tests: the manifest's schema, a resumed run, a hash that differs.

Verification: `make check`, then `make ingest-rules YEAR=2024` on the local stack. Files: the manifest, `raw_store.py`, `cli.py`, an application module, tests, `Makefile`. Size M. Depends on nothing.

#### T8. Splitting an edition into articles

- [ ] `domain/rules.py`: one parser per numbering format, one chunk per numbered sub-article with its number, title, page and text; a long article split at its points.
- [ ] `pypdf` added (approved in ADR 0024) and used by the CLI only.
- [ ] Tests on synthetic text in both formats; hypothesis properties: no text lost, numbers in order.

Verification: `make check`, `make mutation`. Files: `domain/rules.py`, its test, the CLI's extraction, `pyproject.toml`, `uv.lock`. Size M. Depends on T7.

#### T9. The rule store and `make embed`

- [ ] **Ask first:** migration `r0006` with `rule_edition` and `rule_chunk`, `embedding vector(1024)` and an HNSW index with `vector_ip_ops`.
- [ ] `adapters/rule_store.py` and an embedder port; `application/embedding.py` is the reconciling sweep (content hash, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`, `CHUNKER_VERSION`).
- [ ] Tests on pgvector in a container with a fake embedder: a rerun embeds nothing, a changed chunk only that one.

Verification: `make check`. Files: the migration, the store, the use case, the CLI, tests. Size M. Depends on T8.

#### T10. The Voyage adapter

- [ ] `adapters/embeddings.py` calls the embeddings endpoint with `httpx2`, checked against Voyage's API reference when written; `input_type` `document` and `query`, batch limits, its own rate limit, retries on 429 and 5xx only, a timeout.
- [ ] Tests against recorded responses.
- [ ] **Ask first:** the first real `make embed YEAR=2024` spends cents.

Verification: `make check`, then `make embed YEAR=2024` twice, the second embedding nothing. Files: the adapter, its test, settings. Size S. Depends on T9.

#### T11. `search_rules`

- [ ] The edition in force at a race as a pure function: the race's own season, latest date on or before `date_start`, ties by issue then revision; none before the season's first issue.
- [ ] Ranking by distance in one edition, `RULES_MIN_SCORE`, `RULES_TOP_K`; nothing passing means the tool says no article matches.
- [ ] The `article` source with an excerpt capped by `RULES_EXCERPT_MAX_CHARS` and the FIA's URL at `#page=N`; the panel shows it.
- [ ] Tests: next season's issue published during this one is not chosen, the two issues of 2024's Issue 6, an empty retrieval.

Verification: `make check`, `make mutation`. Files: `domain/rules.py`, the tools module, the panel, tests. Size M. Depends on T1, T5, T10.

**Checkpoint B.** "Why was there a safety car" on a 2024 race is answered with a `race_control` row and an article of the edition in force that day. **Ask first:** cents. Review with the author.

### Slice D: limits, budget and refusals

#### T12. The budget and concurrent answers

- [ ] A Redis adapter: concurrent answers counted across instances (`assistant_busy`); the reservation in integer micro-dollars against the UTC day and month, undone when it would pass either; replaced by the real cost when the answer ends, for any reason; the provider's limit sets a pause flag until the end of the month.
- [ ] `GET /api/assistant` answers `paused` with `resumes_at`; `POST /api/answers` answers 503 `assistant_paused`.
- [ ] Tests with a fixed clock: a day's limit, a month's limit, the turn of a day and of a month, two answers reserving at once, the reservation released after an error.

Verification: `make check`. Files: a budget module in application, its Redis adapter, the route, tests. Size M. Depends on T3 and T4.

#### T13. The edge and the answer log

- [ ] nginx: the `answers` zone (6 per minute, burst 2), buffering off and a read timeout above `ASSISTANT_ANSWER_TIMEOUT_S`; `make edge-check` covers both.
- [ ] One `answer` log line: request id, outcome or code, tools in order, rounds, the four token counts, cost and duration, the question's length and the first 12 hex of its SHA-256. A test asserts the question and the keys never appear.

Verification: `make check`, `make edge-check` on the stack. Files: `frontend/nginx.conf`, `infra/edge-check.sh`, the use case or route, tests. Size S. Depends on T12.

#### T14. Refusals and the paused state in the tab

- [ ] The `declined` event shows the reason and offers its suggestion with one tap.
- [ ] The `paused` state: a short notice and the recorded example replayed with its timing (spec, criterion 9). The `disabled` state: a short notice. In both, the replay and simulator tabs keep working.
- [ ] A test parses the recorded example with the generated event types. Until T15 records the real one, the test uses a small hand-made recording, and T15 replaces it.

Verification: `make check`. Files: `frontend/src/assistant/`, `frontend/public/`. Size M. Depends on T5 and T12.

**Checkpoint C.** Each limit of success criterion 8 ends the answer with its own code on the local stack, and the tab shows the paused state with the budget set to zero. Review with the author.

### Slice E: the golden questions and the close

#### T15. The golden questions and `make assistant-eval`

- [ ] About 20 questions: facts, what if and rules, out of scope, no relevant retrieval, English and Spanish. Each expected answer checked by hand against the clean model, with its `session_key`, drivers and laps recorded.
- [ ] The suggestions of `GET /api/assistant` are among them.
- [ ] `make assistant-eval` runs them against the real model and reports per question: citations, the numbers checked, calls of a data tool where there should be none, the time to the first step, the duration and the cost; and the p90 and the mean.
- [ ] **Ask first:** each run spends credits (about 2 USD at the spec's target). The results tune `RULES_MIN_SCORE` and `ASSISTANT_ANSWER_RESERVE_USD`, and changing a limit's value is also asked first.
- [ ] Record the example answer of T14.

Verification: `make check` stays free of credentials; one eval run meets success criteria 1 to 7. Files: the questions, the eval command, `Makefile`, the recording. Size M. Depends on T1 to T14.

#### T16. Close the phase

- [ ] `README.md` and `README.es.md` describe the assistant and its commands; `AGENTS.md` moves phase 6 to Done and lists the new paths; the spec's status is closed.

Verification: `make check`. Size S. Depends on T15.

## Before the first live call

- The author sets the workspace's spend limit to 25 USD in the Claude Console (ADR 0022), and creates the Anthropic and Voyage keys, kept in `.env` only.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Streamed citations on `search_result` blocks do not behave as documented | High: ADR 0021 rests on them | T4 comes before the tab, with recorded responses; a mismatch reopens ADR 0021 then |
| The FIA's PDFs extract badly (margin column, page breaks inside an article) | Medium: wrong or merged article numbers | The extraction check opens T7; the splitter's properties catch lost text |
| Real cost per question above 0.10 USD | Medium: fewer questions a month | Caching from T4, result caps, the eval reports it; the reserve follows the measured maximum |
| The FIA objects to the private index | Low now | ADR 0024: only the manifest and `make embed` change |
| The answer's timeout and the SDK's timeout race each other | Medium: an answer ends with the wrong code | T3's settings refuse an SDK timeout not below the answer's |

## Open questions

- Which seasons the clean model holds when T7 starts decides the manifest's editions. It is checked then, on the local stack.
