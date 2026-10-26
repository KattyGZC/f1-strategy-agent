---
name: tech-audit
description: >-
  Fresh-eyes clean-code review of a branch, a PR or the whole repo, with a ship verdict.
  Trigger after a phase or a large change, before a PR is marked ready, or when asked to
  "audit", "review the code", "is this clean", "audita".
---

# Tech audit

Review as if you did not write the code: you just cloned the repo and have to continue it, or you are a senior engineer deciding whether to hire its author. Hunt for what makes it hard to trust or to change. The standard is `AGENTS.md` plus the accepted ADRs in `docs/adr/`.

## Scope

- Branch or PR: `git diff main...HEAD` (or `gh pr diff <n>`). Judge what changed, and say when a change makes nearby code inconsistent.
- Whole repo: every source file, the tests, the config, the CI workflows, the compose files, the README and the docs.

Read every file in scope. Run the checks in "Before presenting work" (`AGENTS.md`) and the mechanical checks in `.claude/skills/self-grade/SKILL.md`, and quote the results.

## What to look for

**Can a newcomer run and continue it?**
- One command brings the stack up locally; the README commands work as written.
- The README says what exists, not what is planned. `AGENTS.md` "Status" and "Where things are" match the tree.
- Every environment variable the code reads is in `.env.example`.

**Is the architecture what the docs claim?**
- Domain imports nothing from adapters. An SDK imported outside its adapter.
- A use case that builds its own clients instead of receiving them.
- Business rules in HTTP routes, SQL, the frontend or a prompt.

**Is the pipeline correct under load and failure?**
- Blocking I/O in coroutines. Unbounded fan-out. A rate limit enforced by `sleep` in a loop instead of in the adapter.
- Ingestion that a crash halfway leaves marked as done. Retries without a limit.
- Replay order that depends on arrival order. Joins by time proximity. Naive timestamps.
- Background tasks nobody awaits or cancels.

**Is the data honest?**
- Numbers stored as strings. Per-season facts keyed globally (a driver's team).
- Missing uniqueness where the code upserts. Missing indexes on filtered columns, or on the vector column.
- A migration that drops data, or one edited after it ran.

**Is the predictive engine trustworthy?**
- Untested branches (read the coverage report's uncovered lines). Golden cases without a source or tolerance.
- Units mixed (ms and s, kg and laps of fuel) or hidden in names.
- Non-reproducible output for the same inputs and seed.

**Is the assistant grounded?**
- A number in an answer that no tool returned. Retrieval over model-written prose.
- No path for "I do not have that data". Prompts or model names scattered across modules.

**Does the code speak for itself?**
- Functions past ~40 lines, names without unit or meaning, one concept with several names.
- Repeated branching on the same value that one shape per case would remove.
- Comments a rename would make unnecessary.

**Is it shippable?**
- CI runs what `make check` runs. Images build. Deploy is one step from `main`.
- Secrets in git history, images or logs. Dependencies nobody imports. A lockfile missing from git.
- A rule in `AGENTS.md` that a lint rule could enforce instead of a reviewer.

## Output

```
## Tech audit: <scope>: SHIP | ACCEPT-WITH-FIXES | DO-NOT-SHIP

Commands: <each with exit code>

### Findings
| # | Severity | File:line | Issue | Fix |
|---|---|---|---|---|

### Edge cases checked
- [x] ...

### What is already good
<two or three lines, so the fixes do not undo it>
```

Severity: **High** (wrong data or prediction, an invented fact in an answer, a broken contract, a leaked secret, or a newcomer is blocked), **Medium** (hard to read or change safely), **Low** (polish). Any High is DO-NOT-SHIP.

Every finding cites a file and line you read in this session. Do not report something you inferred without opening the file.
