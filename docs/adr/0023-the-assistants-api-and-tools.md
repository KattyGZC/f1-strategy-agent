# 0023. The assistant's API: a status, one POST answered as a stream of typed events, and a closed set of tools

- Status: Accepted
- Date: 2026-11-23

## Context

The spec asks for a tab that shows suggested questions, streams the agent's steps before its first word, cites every fact with a link that opens its source, refuses out-of-scope questions with an in-scope suggestion, and shows a paused notice with a recorded example when the budget is spent (`docs/specs/phase-6-assistant.md`). The API's conventions are set:

- Resources are plural nouns created by a `POST` (`/api/simulations`, `/api/replays`).
- Errors have one shape with a closed `ErrorCode` (ADR 0016).
- A stream is SSE whose `event` is the payload's `kind`, with the payload models in the route's annotation so they reach the OpenAPI document and the generated client (`adapters/http/replays.py`, `watch_replay`).

## Options

1. **`POST /api/assistant` streaming free text, with citations as markers in the text.** One route; but the client would parse the model's markers, and the paused state would be found only by asking a question.
2. **A status resource, `POST /api/answers` answered as SSE of typed events, and citations as events of their own.** The tab knows its state before the first question; every part of an answer is typed in OpenAPI.

## Decision

Option 2, with the tools below as the only things the model can call.

## Consequences

**`GET /api/assistant`** answers `{state, resumes_at, suggestions}`.
- `state` is `available`, `paused` or `disabled`; `resumes_at` is UTC or null.
- `suggestions` holds 4 to 6 `{suggestion_id, question}`, defined in the backend next to the golden questions, since each must be answerable from the clean model.

**`POST /api/answers`** takes `{question}`, 1 to `ASSISTANT_QUESTION_MAX_CHARS` characters after trimming, and answers `text/event-stream`. Before the stream starts, the errors use the shape of ADR 0016:

| Status | `code` | When |
|---|---|---|
| 422 | `invalid_request` | The question is empty or too long |
| 503 | `assistant_disabled` | `ASSISTANT_ENABLED` is false |
| 503 | `assistant_paused` | The budget or the provider's spend limit is reached; the body adds `resumes_at` |
| 503 | `assistant_busy` | `ASSISTANT_MAX_CONCURRENT` answers are running |
| 429 | `rate_limited` | The edge's `answers` zone (ADR 0022) |

**The events.** Each event's SSE `event` is its `kind`, from the closed `AnswerEventKind`. No event has an `id`: an answer cannot be resumed, and a lost connection means asking again.

| `kind` | Payload | Meaning |
|---|---|---|
| `step` | `step`, `tool`, `status` | `running` when a tool starts; then `done`, `empty`, `rejected` (its input failed validation) or `failed`, for the same `step` |
| `text` | `delta` | The next piece of prose |
| `citation` | `number`, `source` or null | A citation at this point of the text. `source` is sent the first time a number appears, null after |
| `declined` | `reason`, `suggestion_id` | The question is out of scope; the tab offers that suggestion |
| `done` | `outcome` | `answered` or `declined`; the stream ends |
| `error` | `code`, `detail`, `request_id` | The answer ended early; the stream ends |

- An `error` event's codes are `answer_timeout`, `tool_rounds_exceeded`, `answer_too_long` (a turn reached its output tokens), `assistant_paused`, `model_unavailable` (the provider is overloaded or failing after its retries), `model_refused` (stop reason `refusal`) and `internal_error`.
- Every code, before or during the stream, is a value of the one `ErrorCode` enum.
- The edge proxies `/api/answers` with buffering off and a read timeout above `ASSISTANT_ANSWER_TIMEOUT_S`.

**`source`** is a union discriminated by `kind`. It holds what the tool returned in this answer, so opening a citation needs no other request:

- `row`: `table` (enum: `session_result`, `starting_grid`, `stint`, `pit`, `lap`, `race_control`, `weather`), `session_key`, the race's name and year, the row's key (`driver_number`, `lap_number`, `stint_number`, `seq` or `date`, as the table's primary key has them) and its values as the tool returned them.
- `article`: season, edition and its date, article number (`55.1`, `B5.10.1`), its title, the cited excerpt (at most `RULES_EXCERPT_MAX_CHARS`, 600) and the URL of the FIA's PDF with its page (ADR 0024).
- `simulation`: the strategies asked for and the simulator's response, as `POST /api/simulations` returns it.

A citation opens a panel inside the Assistant tab that shows its source. Jumping to the replay at a lap would need the replay screen's state in the URL, which ADR 0018 does not have; it is left out of V1.

**The tools**, the closed enum `ToolName`. Each input is a Pydantic model whose JSON schema is the tool's `input_schema`:

| Tool | Input | Returns, at most |
|---|---|---|
| `find_races` | `year`, `name`, both optional | Races of the clean model: `session_key`, name, date, whether calibrated |
| `race_results` | `session_key` | The classification and the starting grid, with each driver's number, name and team |
| `driver_strategy` | `session_key`, `driver_number` | The driver's stints and pit stops |
| `lap_times` | `session_key`, `driver_number`, `from_lap`, `to_lap` | `ASSISTANT_TOOL_MAX_ROWS` laps |
| `race_control` | `session_key`, `from_lap`, `to_lap`, `category`, all but the first optional | `ASSISTANT_TOOL_MAX_ROWS` messages |
| `weather` | `session_key` | Readings every 10 minutes, at most 30 |
| `search_rules` | `query` (at most 200 characters), and exactly one of `session_key` or `season` | `RULES_TOP_K` articles of the edition in force at that race, or of the season's latest edition (ADR 0024) |
| `simulate_strategies` | The body of `POST /api/simulations` | The simulator's response; one `simulation` source |
| `decline_question` | `reason` (enum: `future_race`, `live_data`, `season_not_loaded`, `not_formula_1`, `other`), `suggestion_id` | Nothing: the answer ends `declined` |

- A result larger than its cap is cut, and the tool says so in its result, so the model can narrow the next call.
- `decline_question` makes the refusal of success criterion 5 structured. The suggestion is one of ours, by id, never text from the model. A test asserts that an out-of-scope golden question calls no data tool.

**The recorded example** shown when the assistant is paused is a real answer's events, recorded once into `frontend/public/` with the event format's version. The tab replays it with its timing. A frontend test parses it with the generated event types, so a change of the event format fails until it is recorded again.

**Labels.** The frontend owns the step labels ("Querying laps…") and every word of the interface, in English (issue #13). The answers follow the question's language.
