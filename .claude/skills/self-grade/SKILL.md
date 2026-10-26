---
name: self-grade
description: >-
  Grade your own finished work against AGENTS.md before presenting it. Trigger when a task
  or a phase item is done, before a commit or PR, or when asked "is it ready", "are you
  done", "show me", "¿está listo?".
---

# Self-grade

Source: `AGENTS.md` and the accepted ADRs in `docs/adr/`. Grade only the rows that apply to the change; mark the rest N/A with a few words of why.

## Protocol

1. Re-read `AGENTS.md` and every ADR the change touches.
2. List every file created or modified: `git status --short` and `git diff --stat main...HEAD`.
3. Run the commands in "Before presenting work" (`AGENTS.md`). Quote each exit code. Do not paraphrase output you did not see. If a check does not exist yet, say so in the Commands line.
4. Run the mechanical checks below on the changed files.
5. Fill in the table. Every applicable row needs evidence: file:line, command output, test name. Empty evidence is **F**. An inferred claim cannot earn more than **B**.
6. Fix every row below **A** through its owner, and re-grade. Present only when every applicable row is **A**.

## Hard stops (overall F, whatever the other rows say)

- The path is `around` the owner, or the change does not survive a reset (wipe volumes, run the stack and ingestion again).
- A number in an assistant answer that no tool returned.
- A field, enum value, endpoint or column invented because a source was silent.
- A secret staged, logged, printed or sent in a prompt.
- A lap-time, degradation or strategy computation outside the domain model.

## Mechanical checks

Paths follow the layout phase 0 creates; adjust them to "Where things are" in `AGENTS.md` and quote what you ran.

```bash
# Domain purity: must print nothing
git grep -nE "^\s*(from|import) (sqlalchemy|fastapi|httpx|requests|pydantic_settings|motor|pymongo|redis|ollama|anthropic|openai|langgraph|boto3)|datetime\.now\(|time\.time\(|random\.(random|randint|choice)\(" -- '*/domain/*'

# Blocking calls in async code: review every hit
git grep -nE "\brequests\.|time\.sleep\(|psycopg2|\.query\(" -- '*.py'

# Naive datetimes: review every hit
git grep -nE "datetime\.(utcnow|now)\(\)|DateTime\(\)|DateTime\b[^(]" -- '*.py'

# Any and casts: review every hit
git grep -nE ":\s*Any\b|-> Any\b|\bcast\(|# type: ignore|:\s*any\b|\bas (any|unknown)\b" -- '*.py' '*.ts' '*.tsx'

# Comments added by this change: classify each one
git diff main...HEAD -U0 -- '*.py' '*.ts' '*.tsx' | grep -E "^\+.*(#|//|/\*)" | grep -vE "^\+\s*#!|noqa|type: ignore"

# Unbounded fan-out: each hit needs a named bound
git grep -nE "asyncio\.gather\(\*|create_task\(" -- '*.py'

# Secrets in the diff: must print nothing
git diff main...HEAD | grep -nEi "(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"<]{8,}"

# Every new top-level path is listed in AGENTS.md "Where things are"
git diff --name-only --diff-filter=A main...HEAD | cut -d/ -f1 | sort -u
```

## Table

| Row | Check | Grade | Evidence |
|---|---|---|---|
| Why | One sentence of the outcome was written before the first edit | | |
| Owner | Owner check in the thread; path through; survives reset | | |
| Evidence | Every load-bearing claim proven with an artifact | | |
| Scope | Smallest change through the owner; no refactor of nearby code | | |
| Decisions | No ADR or `AGENTS.md` decision reversed without saying so | | |
| Layers | Domain pure (grep empty); adapters own their SDKs; use cases receive adapters | | |
| Determinism | Joins by ids; explicit tie-breaks; UTC-aware timestamps; idempotency keys from the source; seeded randomness | | |
| Async | No blocking call in a coroutine; bounded concurrency; rate limit in the adapter; retries limited | | |
| Data | Schema is the contract; numbers typed; per-session drivers; migration one-way; parameterized; no N+1 | | |
| Model | Numbers in answers come from tools and are cited; embeddings over source material; prompts in one adapter | | |
| Names | Unit and meaning in names; one name per concept | | |
| Functions | One job each; longest function named with its length; nesting at most 3 | | |
| Types | `mypy --strict` / `tsc --strict` clean; no unjustified `Any` or cast; unions over boolean pairs | | |
| Constants | Closed sets are enums or `Literal`, defined once; raw API values mapped at the boundary | | |
| Comments | Each new comment is a non-obvious why or a needed docstring (quote the count) | | |
| Fail loud | No catch-log-continue; failures name what is missing | | |
| Tests | Behavior tested with edge and negative cases; full expected values; on a path CI runs (name the command) | | |
| Sabotage | Broke the function once, named the test that went red, restored | | |
| Golden | Golden cases pass when the model changed; a new case records its source and tolerance | | |
| Security | Input validated at the boundary; secret grep empty; `.env.example` updated for new variables | | |
| Docs | README describes what exists; ADR for a lasting decision; "Status" and "Where things are" updated | | |
| Dead code | Old implementation grepped and deleted; no unused imports, files or branches | | |
| Git | Feature branch; commits split by layer; commit plan shown before committing | | |

## Output

```
## Self-grade: <task>
Files: <paths>
Commands: <each with exit code, or "does not exist yet">

<table>

### Fixed during grading
1. <row>: <what was wrong> → <fix>

### Overall: A
```

Any applicable row below **A** means the work is not ready. Fix it before presenting.
