# 2026-11-05 · 01. Quality gates for agent-written code

**Goal:** code the agent writes wrong fails before it runs, and red CI reaches `main` only when the owner chooses.

## What happened

1. The author asked whether the repo had linters and formatters that catch errors before running the project, and how to notice the agent writing wrong code, code without logic, or patches (translated). The agent audited the toolchain: strict and clean, but nothing forced it to run, the ruleset on `main` blocked nothing, and several `AGENTS.md` rules lived only as prose.
2. The author asked for it as a detailed issue with a proposal ([#7](https://github.com/KattyGZC/f1-strategy-agent/issues/7)), then changed the merge policy in it (see Corrections), then asked to take the issue and solve it.
3. Built on `chore/quality-gates` in six commits by layer; the ruleset was applied with `gh api` after the author's OK. [PR 9](https://github.com/KattyGZC/f1-strategy-agent/pull/9).

## Decisions

- **Where red code stops and who merges past it**: [ADR 0010](../adr/0010-quality-gates.md). Claude Code hooks run `make fast-check` before a commit and before a stop; `main` requires the four CI checks; the admin role bypasses for pull requests only; the agent is denied `gh pr merge` and ruleset calls, because it runs `gh` with the owner's token.
- **One owner per SDK, pydantic excepted**: the CLI asks `raw_store` and `openf1` for clients, as it already did for PostgreSQL and Redis, instead of recording it as an exception.
- **`TRY003` stays off**: it wants one exception class per message, against "name what is missing".
- **mutmut in a container**: it needs `fork()`, so `make mutation` runs on Linux the same way on every host, not through WSL.
- **The 60 surviving mutants are their own PR**: they are real gaps, about 40 domain tests, a different concern from the gates.

## Corrections and redirections

- The issue first proposed that red CI blocks every merge. The author chose "let's not require everything green to merge to main, but restrict it so only I, as the repo owner, can merge even with reds" (translated). The agent added the admin bypass for pull requests only, and the deny on `gh pr merge` once it saw the agent itself holds the owner's token.
- The first oxlint config turned on `suspicious`, which carries `react-in-jsx-scope`, wrong under the automatic JSX runtime; turned off with its reason.
- The first mutation run copied the host's `__pycache__` and missed the application layer, and the use case tests failed to import; fixed with `--exclude=__pycache__` and `also_copy`.
- The suppression check used `git grep`, blind to untracked files, so the stop hook would miss a new file; it now passes `--untracked`.

## Verification

- `make check`: exit 0. Backend 373 tests at 100% branch coverage; 3 import contracts kept; frontend and the OpenAPI contract green.
- Sabotage of every new gate (import contracts, nine ruff rules, `exhaustive-deps`, an unexplained `noqa`, the replay tie-break): each went red, each restored.
- Hook script piped four cases: commit green 0, commit red 2, stop red 2, second stop red 0 with a user message.
- `make mutation`: 1,451 of 1,513 mutants killed, 60 survived, 2 timeouts.
- Not verified: the hooks firing in this session (Claude Code only watches `.claude/` if it held settings at start), and a direct push to `main` being rejected.

## Next

- Open `/hooks` or restart so the hooks load, then watch CI on PR 9.
- Kill the 60 surviving domain mutants in their own PR.
