# Spec: Phase 6, the assistant (V1)

- Status: approved by the author on 2026-11-22
- Date: 2026-11-22
- Decisions it leads to are recorded as ADRs; this spec does not replace them.

## Intent

Confirmed with the author on 2026-11-22 (interview, session 1 of phase 6):

- **Outcome:** a Formula 1 strategy assistant that answers in a live stream, shows its steps ("querying laps…", "simulating…") and cites every fact with a link that opens the source.
- **User:** built with recruiters and interviewers in mind, without saying so anywhere. Anyone else is welcome to use it.
- **Why now:** phases 0 to 5 built the data, the lap-time model and the simulator. They are the assistant's tools.
- **Success:** within a minute, a visitor taps a suggested question, watches the agent reason with tools, and opens a citation that leads to the real data.
- **Constraint:** at most 25 USD a month of model usage. Quality before savings.
- **Out of scope:** see the last section but one.

## Objective

A new Assistant tab answers one question at a time about the races in the clean model. It handles three kinds of question:

1. **Facts:** "How many stops did Norris make at Monza 2024, and on which compounds?"
2. **What if:** "Should Leclerc have stopped twice at Monza 2024?" Answered by the phase 5 simulator, with its caveats.
3. **Rules applied to a race:** "Why was there a safety car on lap 30?", "What do the rules say about using two compounds?" Answered by crossing race control with the FIA Sporting Regulations.

The model chooses tools and writes prose. Every number, position, gap, compound and rule in an answer comes from a tool result and is cited (`AGENTS.md`, Model and RAG).

### User stories

- As a visitor, I see four to six suggested questions and can answer any of them with one tap.
- As a visitor, I can type my own question in English or Spanish and get the answer in the same language.
- As a visitor, I see each step the agent takes while it works, before the first word of the answer arrives.
- As a visitor, I can open each citation and see the row or the regulation article it points to.
- As a visitor, when I ask something outside the scope, I am told so and offered a question the assistant can answer.
- As a visitor, when the month's budget is spent, I see a short notice and a recorded example answer, and the replay and simulator tabs still work.
- As the author, I can trace any answer to its request id, its tool calls, its token usage and its cost in the logs.

## Tech stack

Additions to what phases 0 to 5 use (Python 3.12 with uv, FastAPI, PostgreSQL 17 with pgvector, MongoDB, Redis, React with Vite and TypeScript, nginx):

- **Language model:** Claude Opus 5.5 (`claude-opus-5-5`) through the official `anthropic` Python SDK, async client, streaming. The model name is a setting.
- **Embeddings:** Voyage AI through its official Python SDK. The model and its dimension are settings, fixed by the migration that declares the vector column.
- **Vector store:** pgvector in the existing PostgreSQL (ADR 0002), HNSW index declared in a migration.
- **Rules source:** the FIA Formula 1 Sporting Regulations of each season in the clean model, stored as received in the document store before they are split and embedded.

Exact package versions are pinned in `uv.lock` when they are added.

## Commands

Existing, unchanged: `make install`, `make check`, `make fast-check`, `make mutation`, `make edge-check`, `make openapi`, `make up`, `make migrate`, `make ingest YEAR=...`, `make transform YEAR=...`, `make calibrate YEAR=...`.

New (names proposed, fixed in the plan):

```
make ingest-rules YEAR=2024   # stores the season's Sporting Regulations as received
make embed YEAR=2024          # splits and embeds what changed since the last run
make assistant-eval           # runs the golden questions against the real model; spends credits, run by hand
```

`make check` never calls the model or the embeddings provider.

## Project structure

Within the existing layers (`AGENTS.md`, Architecture); file names are proposals:

```
backend/src/f1_strategy/domain/assistant.py         → question, answer, citation, tool names, stream event types (enums)
backend/src/f1_strategy/domain/rules.py             → regulation articles and how a document is split
backend/src/f1_strategy/application/assistant.py    → the answer use case: the tool loop and its limits, behind ports
backend/src/f1_strategy/application/embedding.py    → the reconciling embed sweep
backend/src/f1_strategy/adapters/language_model.py  → the only importer of anthropic; prompts and model name live here
backend/src/f1_strategy/adapters/embeddings.py      → the only importer of the Voyage SDK
backend/src/f1_strategy/adapters/rule_store.py      → chunks and vectors in PostgreSQL
backend/src/f1_strategy/adapters/http/assistant.py  → POST /api/assistant, answered as SSE
backend/src/f1_strategy/adapters/migrations/        → the chunk table, its vector column and HNSW index
frontend/src/assistant/                             → the Assistant tab
docs/specs/                                         → this spec
docs/adr/                                           → the phase's decisions
```

## Code style

The existing style holds: frozen dataclasses in the domain and application, ports as `Protocol`, closed sets as enums, use cases that receive their adapters. From `application/simulation.py`:

```python
class CalibratedRaces(Protocol):
    async def calibration(self, session_key: int) -> Calibration | None:
        """The race's stored calibration, or None if the race is not calibrated."""
        ...


class ListRaces:
    def __init__(self, races: CalibratedRaces) -> None:
        self._races = races
```

The assistant's model port follows the same shape: the use case knows a `LanguageModel` protocol, never the SDK.

## Testing strategy

- **Unit, domain:** pytest with hypothesis where a property exists (splitting a document, citation spans). Covered by `make mutation`.
- **Use case:** the tool loop against a scripted fake model and fake tools. It covers the end of an answer, each limit reached, an invalid tool argument, a tool error, an empty retrieval and the paused state. No network, no credits.
- **Adapters:** PostgreSQL and pgvector with testcontainers, as the existing store tests do. The Anthropic and Voyage adapters are tested against recorded responses, never live.
- **HTTP:** the SSE route's event order, error codes and request id.
- **Edge:** `make edge-check` covers the assistant's rate limit and SSE settings.
- **Frontend:** vitest for the tab: streaming text, steps, citations, the paused notice.
- **Golden questions:** about 20 questions with answers checked by hand against the clean model. They cover each question kind, out-of-scope questions and both languages. They run with `make assistant-eval` only, and each run reports its cost.
- Coverage stays at or above the existing 90 % gate.

## Boundaries

- **Always:** numbers come from tool results and are cited. Tool arguments are validated before a tool runs. Every limit is a named setting. Tests run without network or credits. Each SDK is imported by its one adapter, and import-linter enforces it.
- **Ask first:** adding a dependency, a schema migration, changing a limit's value, changing the model, any step that spends credits (an eval run, a live check).
- **Never:** a tool that writes, deletes or reaches the internet. SQL written by the model. A secret in a prompt, a log line or the frontend. The question text logged whole. A server tool (web search, web fetch, code execution).

## Success criteria

Each one is checked by a test, a command or the golden questions:

1. The Assistant tab shows 4 to 6 suggested questions. Each is answered with at least one citation in every golden run.
2. In the golden run, every number in an answer matches the clean model, and every citation opens the row or the article it names.
3. The first step event reaches the browser within 3 s of the question at the p90 of the golden run. The answer completes within 60 s, or ends with a clear "took too long" message.
4. The mean cost per golden question is at most 0.10 USD, so 25 USD covers about 250 questions a month.
5. An out-of-scope question gets a refusal and a suggested in-scope question, with no tool call that reads data.
6. A question with no relevant retrieval says so, instead of answering from the model's memory.
7. The answer is in the language of the question, English or Spanish.
8. Each limit, once reached, ends the answer with its own error `code` and leaves the stream well formed. The limits are question length, tool rounds, answer tokens, time per question, concurrent answers and requests per address at the edge.
9. When the provider reports the spend limit is reached, `/api/assistant` answers with a dedicated `code`. The tab shows the paused notice and a recorded example answer, and the replay and simulator tabs keep working.
10. The logs hold one line per answer with the request id, tools used, input, output and cached tokens, cost and duration, and never the API keys.
11. `make check` passes with no credentials set.

## Out of scope (deferred)

- **Follow-up questions in a conversation:** V1 answers one question at a time. Memory across turns raises cost and complexity, and the demo's minute does not need it.
- **Predictions of future races and live data:** the project replays settled sessions (ADR 0001).
- **Seasons not in the clean model, general F1 history, non-F1 topics:** no source to cite.
- **Login and per-user quotas:** phase 7.
- **Feedback buttons and saved conversations:** nothing in V1 reads them.
- **A Spanish interface:** issue #13. The answers already follow the question's language.
- **A local model for development:** the port allows it, but V1 tests use the fake model.

## Open questions

The author agreed to each proposal below on 2026-11-22. Session 2 (design) records them in ADRs, and settles question 5, which needs the provider's documentation:

1. **Which seasons' regulations.** The clean model holds more than one season, and 2026 runs under new regulations. Is each season's Sporting Regulations indexed and searched by the season of the race asked about? Proposed: yes.
2. **Race control: query or search.** Proposed: race control messages are reached through `query_stats` (filtered by session and lap), not embedded, because they are rows with ids. Only the regulations are embedded.
3. **Where the regulations come from.** The FIA publishes them as PDFs. Is the PDF downloaded by `make ingest-rules` from its published URL, or committed to the repo? Proposed: downloaded and kept in the document store, like OpenF1 data.
4. **Missing API keys.** Does the backend refuse to start without them, or start with the assistant off through an explicit setting? Proposed: an explicit `ASSISTANT_ENABLED` setting. When it is true, the keys are required.
5. **How the spend limit shows up.** Which error the provider returns when the workspace limit is reached, verified in its documentation (session 2, source-driven). Whether a daily token budget of our own is also needed.
6. **The limit values.** Proposed starting values: a question of at most 500 characters, 6 tool rounds, 60 s per answer, 4 answers at once, 6 questions a minute per address. Fixed in the design ADR.
7. **The recorded example answer.** It is a real stream recorded once and served as a static file by the frontend. It is re-recorded when the event format changes.
