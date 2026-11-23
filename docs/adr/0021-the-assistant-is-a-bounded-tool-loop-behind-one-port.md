# 0021. The assistant is a bounded tool loop behind one port, without an agent framework

- Status: Accepted
- Date: 2026-11-23

## Context

Phase 6 adds the assistant (`docs/specs/phase-6-assistant.md`). The model chooses tools and writes prose; every number in an answer comes from a tool result and is cited (`AGENTS.md`, Model and RAG). The spec names Claude Opus 5.5 (`claude-opus-5-5`) through the official `anthropic` Python SDK, and asks that each citation open the row or the article it names. Facts checked in the provider's documentation on 2026-11-23:

- A client tool can return `search_result` blocks, and with `citations: {"enabled": true}` the model's text arrives split into text blocks, the cited ones carrying `search_result_location` citations with the `source` string we gave the block, its `title` and the `cited_text`. "Claude cites whole blocks, not substrings." If any block of a `tool_result` is a `search_result`, all of them must be, and citations are enabled for every search result of a request or for none. https://platform.claude.com/docs/en/build-with-claude/search-results
- While streaming, "citations arrive as a `citations_delta` delta type inside `content_block_delta` events", after the text of their block; the Python SDK's `messages.stream` yields them as `CitationEvent`. https://platform.claude.com/docs/en/build-with-claude/citations
- Prompt caching applies to tools, then system, then messages, from a 512-token minimum on Opus 5.5; a cache read costs 0.05x the input price on Opus 5.5. https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- `stop_reason` is one of `end_turn`, `tool_use`, `max_tokens`, `stop_sequence`, `pause_turn`, `refusal`, `model_context_window_exceeded`, and new event types may appear in a stream. https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons
- `anthropic` 2.12.0 is Apache-2.0 and depends on `httpx2`, the HTTP client the backend already uses (https://pypi.org/pypi/anthropic/json). The author approved adding it on 2026-11-23.

## Options

1. **An agent framework (LangChain, LangGraph, LlamaIndex, Pydantic AI).** Ready-made loops, retrievers and provider swapping. Its types would cross every layer, against the one-adapter rule (ADR 0010); provider features such as search-result citations arrive late or flattened; the dependency graph is large and its API changes often. Swapping providers is already what the port gives.
2. **The Claude Agent SDK.** Built for agents that act on files and shells; the assistant needs neither, and it would bring server-side tools the spec forbids.
3. **Our own loop in the application layer, the SDK in one adapter.** About a hundred lines, each limit visible and tested with a scripted fake model; the provider's citations are mapped to our own type at the adapter.

## Decision

Option 3. The answer use case runs a bounded loop of model turns and tool calls against a `LanguageModel` port; `adapters/language_model.py` is the only importer of `anthropic` and holds the prompts and the model name. Citations come from the provider's search-result citations and are kept only when they point at a block a tool returned in the same answer.

## Consequences

- **The port.** `LanguageModel.turn(transcript, tools)` streams one model turn as our own events (a text delta, a citation naming a source id, a tool call with its parsed input, the turn's end with its stop reason and token usage). The use case never sees an SDK type. A scripted fake implements it for the tests; a local model can implement it later.
- **The loop.** Ask the model; for each tool call, validate the input with the tool's Pydantic model, run the tool, record what it returned; send the results back; repeat until the model ends its turn, `decline_question` is called, or a limit is reached (ADR 0022). An invalid input or a failed tool goes back to the model as an error result and counts as a round; it never raises out of the loop.
- **Tool results.** Every data tool returns its rows or articles as `search_result` blocks with citations enabled. A block's `source` is our id for what it holds (`row:<table>:<session_key>:<key...>`, `article:<edition>:<number>`, `simulation:<n>`); a tool with nothing to return answers one text block saying so. Results are capped per tool (ADR 0022), so the context stays small.
- **The ledger.** Each answer keeps a map from source id to what the tool returned. A citation whose source is not in the ledger is dropped and logged; one that is becomes a `citation` event with the typed source (ADR 0023). The frontend never receives a source the backend did not produce.
- **Caching.** The tool definitions and the system prompt carry `cache_control`, and so does the last block of each turn's input, so later rounds of the same answer read the earlier ones from the cache.
- **SDK settings.** The model name, `max_tokens` per turn, the SDK's `max_retries` and its timeout are settings. The SDK timeout is shorter than the answer's own (ADR 0022), so a stalled call ends the answer with its own code instead of waiting ten minutes, the SDK default.
- **Unknown events.** The adapter ignores stream event types it does not know, as the documentation asks, and fails the answer on a stop reason it does not know.
- **What it costs.** We own the loop, its retries and its limits, and follow the provider's API changes in one file.
