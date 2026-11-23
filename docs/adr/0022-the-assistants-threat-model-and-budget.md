# 0022. The assistant's threat model: read-only tools, enforced limits and a budget of our own

- Status: Accepted
- Date: 2026-11-23

## Context

The assistant is the first part of the app that spends money per request, and anyone can reach it without logging in (login is phase 7). The spec caps model usage at 25 USD a month and lists the limits to enforce (`docs/specs/phase-6-assistant.md`, success criteria 8 to 10, open questions 4 to 6). The edge already sets a request id, an error shape, body and rate limits and security headers (ADR 0016).

**Assets:** the monthly budget; the Anthropic and Voyage API keys; the credibility of an answer (a made-up number or a citation that opens nothing); the replay and simulator, which must keep working whatever the assistant does. The system prompt is not an asset: it lives in a public repository, so nothing secret may ever go into it.

**Trust boundaries:**

| # | What crosses | Who wrote it |
|---|---|---|
| B1 | The question | Any visitor |
| B2 | The model's tool calls and prose | The model, steered by B1 and B3 |
| B3 | Tool results sent back to the model | OpenF1 (race control messages, names) and the FIA's PDF |
| B4 | Our calls to Anthropic and Voyage | Us, with the keys |
| B5 | The stream the browser renders | The model and us |

How the provider reports a spend limit, from its documentation on 2026-11-23:

- A limit we set on the organization or a workspace returns "HTTP 400 with error type `invalid_request_error`. The message starts with `You have reached your specified API usage limits`, or `You have reached your specified workspace API usage limits`". No error code is documented for this case. https://platform.claude.com/docs/en/api/rate-limits
- The tier's cap returns 429 `rate_limit_error` with `error.details.error_code` `enforced_spend_limit_reached` and no `retry-after`; "Retrying, including the SDK's automatic retries, fails until access resumes." Same page.
- The SDK retries 408, 409, 429 and 5xx twice by default, and a request times out after 10 minutes by default. https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python

## Options

1. **Rely on the provider's spend limit alone.** Nothing to build; but one abusive day spends the month and pauses the demo until the next one, and recognising the limit depends on the text of a 400.
2. **Limits at every layer and a budget of our own, with the provider's limit as the last net.**

## Decision

Option 2. The model can only read, through tools we wrote; every limit is a named setting enforced in code; our own budget of 2 USD a day within 25 USD a month, kept in Redis, decides when the assistant pauses, and the provider's spend limit is the hard cap behind it.

## Consequences

**Prompt injection (B1, B3) is contained in code, not in the prompt.**
- The tools are a closed enum. None writes, deletes or reaches the internet; no server tool (web search, web fetch, code execution) is enabled.
- The model never writes SQL. Each tool runs queries we wrote, with the model's validated values as parameters, in a `READ ONLY` transaction, so PostgreSQL refuses a write even if one of our queries had a bug.
- Every tool input is validated by its Pydantic model before the tool runs: ids are positive, enums are closed, lap ranges and text lengths are bounded. A `session_key` the clean model does not hold is an error result, not a query.
- The worst a hijacked answer can do is say something wrong or off topic within the limits below. Citations cannot be forged: only sources in the answer's ledger reach the browser (ADR 0021).

**Rendering (B5).**
- The answer is rendered as text with React: paragraphs, bullet lines and bold, parsed by our own code into elements. Nothing is rendered as HTML, and anything else, a link written by the model included, stays plain text.
- The only links are the citations, built by the frontend from typed sources (ADR 0023). An article's link is the FIA's URL from our manifest (ADR 0024), never a URL from the model.
- The CSP of ADR 0016 is unchanged.

**Denial of service and of budget, from the outside in.**

| Layer | Limit | Setting (starting value) |
|---|---|---|
| Edge | Questions per address | nginx zone `answers`, 6 per minute, burst 2 |
| API | Question length | `ASSISTANT_QUESTION_MAX_CHARS` (500) |
| API | Answers at once, across instances | `ASSISTANT_MAX_CONCURRENT` (4), counted in Redis |
| Answer | Tool rounds | `ASSISTANT_MAX_TOOL_ROUNDS` (6) |
| Answer | Output tokens per model turn | `ASSISTANT_MAX_OUTPUT_TOKENS` (2048) |
| Answer | Wall time | `ASSISTANT_ANSWER_TIMEOUT_S` (60) |
| Tool | Rows or articles per result | `ASSISTANT_TOOL_MAX_ROWS` (60), `RULES_TOP_K` (5) |
| Budget | Spend per UTC day and per UTC month | `ASSISTANT_DAILY_BUDGET_USD` (2), `ASSISTANT_MONTHLY_BUDGET_USD` (25) |
| Provider | Workspace spend limit | Set to 25 USD in the Claude Console |

- When the browser disconnects, the answer's task is cancelled and the model call with it, so nobody pays for an answer nobody reads.
- The SDK's `max_retries` is `ASSISTANT_MODEL_MAX_RETRIES` (1) and its timeout `ASSISTANT_MODEL_TIMEOUT_S` (45), under the answer's 60 s.

**The budget.**
- Before an answer starts, it reserves `ASSISTANT_ANSWER_RESERVE_USD` against both the day and the month, with an atomic Redis increment in integer micro-dollars. If either total would pass its limit, the reservation is undone and the request is refused with `assistant_paused`.
- The starting value, 0.75, is an estimate, not a measurement: 6 rounds of 2048 output tokens cost about 0.25 USD at 20 USD per million, and 6 rounds whose input grows by one capped tool result and one turn each, without the cache, about 0.45 at 4 USD per million. The golden run reports the real maximum, and the value follows it.
- When the answer ends, for any reason, the reservation is replaced by its real cost. The real cost comes from the usage the provider reports (input, cache write, cache read and output tokens) times the prices, which are settings and never constants in code: `ASSISTANT_PRICE_INPUT_PER_MTOK_USD`, `ASSISTANT_PRICE_CACHE_WRITE_PER_MTOK_USD`, `ASSISTANT_PRICE_CACHE_READ_PER_MTOK_USD` and `ASSISTANT_PRICE_OUTPUT_PER_MTOK_USD` (4, 5, 0.20 and 20 for Opus 5.5, https://platform.claude.com/docs/en/about-claude/pricing).
- With answers running at once, the budget is passed only by what an answer costs above its reservation. Every answer that costs more is logged, and the reserve is raised.
- The keys are per UTC day and per UTC month, and expire after their period; the clock is passed in, so the budget is tested with fixed times. `resumes_at` is the next UTC midnight, or the first day of the next month.
- **The provider's limit** is recognised in the adapter by `error_code == "enforced_spend_limit_reached"`, or by a 400 `invalid_request_error` whose message starts with one of the two documented prefixes. Either case pauses the assistant until the end of the UTC month (Redis flag) and ends the answer with `assistant_paused`; its `resumes_at` is unknown and sent as null. Any other 400 is `internal_error`. If the provider changes that text, the provider's limit shows up as `internal_error` instead of a pause, and our own budget still pauses first.

**Secrets and disclosure.**
- `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` are `SecretStr` settings, read once and never put in a prompt, a log line, an error body or the frontend.
- `ASSISTANT_ENABLED` is a required boolean setting. When false, the keys are not required, `GET /api/assistant` answers `disabled` and `POST /api/answers` answers 503 `assistant_disabled`. When true, a missing key fails the backend's start. `make check` runs with it false.
- Error bodies are generic and carry the request id (ADR 0016); a provider's message is never forwarded.

**The question is personal data in potential.** Visitors can type anything.
- It is sent to Anthropic to be answered, and the `query` the model writes for `search_rules`, which may repeat part of it, is sent to Voyage to be embedded. It is stored nowhere: no conversation memory, no feedback, no saved answers.
- The tab says so in one line.
- Logs never hold its text, only its length and the first 12 hex characters of its SHA-256, to spot repeats.

**Repudiation.** One `answer` log line per answer: request id, outcome or error `code`, tools called in order, rounds, input, cache write, cache read and output tokens, cost in USD and duration (spec, criterion 10).

**Spoofing and elevation of privilege.** There are no users or roles. The request id comes from nginx only (ADR 0016). The model has no permission beyond the read-only tools.

**Supply chain.**
- New dependencies: `anthropic` (ADR 0021) and `pypdf` (ADR 0024), approved by the author on 2026-11-23. Voyage is called over HTTP with the existing client, not through its SDK (ADR 0024).
- The FIA's PDFs are downloaded from fixed URLs listed in a committed manifest with their SHA-256. A download whose hash differs fails `make ingest-rules`. They are parsed only by the CLI, never by the API.
