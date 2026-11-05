# 0010. Quality gates: the agent cannot commit red, main cannot merge red except by its owner

- Status: Accepted
- Date: 2026-11-05

## Context

Most of the code is written by an AI agent. `AGENTS.md` asks it to run `make check` before presenting work, and CI runs the same checks on every pull request, but nothing enforced either (audited 2026-11-04, issue #7):

- No git hook and no Claude Code hook ran anything. The checks ran only if the agent chose to run them.
- The ruleset on `main` blocked deletion and force pushes only. A pull request with red CI could be merged, and `main` took direct pushes.
- Several rules of `AGENTS.md` lived only as prose. One had already drifted: "each external SDK is imported by exactly one adapter module" was broken by `adapters/cli.py`, which imported `pymongo` and `httpx2` itself.
- Coverage was 100% of branches, which says every line ran, not that a test would notice it changing. `mutmut` on the domain later found 60 of 1,513 mutants that no test kills.

## Options

Where to stop red code:

1. **CI only, as required checks.** Catches everything, but late: the agent learns of a lint error after a push.
2. **A pre-commit framework (`pre-commit`).** Runs for every author, but is a second runner with its own copy of the tool list, and the agent can skip it with `--no-verify`.
3. **Claude Code hooks plus required checks.** The hooks run the same `make` target as CI before the agent commits and before it stops; the required checks stop what reaches `main`.

Who may merge red:

1. **Nobody.** A flaky runner or an upstream outage (the mongod kernel issue noted in `ci.yml`) would block every merge.
2. **The repository admin, through a pull request only.** In a personal repository the owner is the only admin; collaborators can get write at most.

## Decision

Option 3 for where, and the admin bypass through pull requests for who:

- `make fast-check` runs every static check (the unexplained-suppression check, ruff, ruff format, `mypy --strict`, import-linter, oxlint, Prettier, `tsc`). `backend-check` and `frontend-check` run it first, so CI runs it too.
- `.claude/settings.json` runs `make fast-check` before every `git commit` the agent makes and before the agent stops with changed files, and blocks on failure. A stop already blocked once is let through with a message to the user, so a check the agent cannot fix does not loop.
- The ruleset on `main` requires a pull request and the `backend`, `frontend`, `contract` and `stack` checks. The repository admin role may bypass it for pull requests only.
- The agent runs `gh` with the owner's token, so to GitHub it is the owner. `.claude/settings.json` denies it `gh pr merge` and any `gh api` call on rulesets: the owner merges, and the agent cannot loosen the gate.
- Rules a tool can enforce are enforced by the tool: ruff families for commented-out code, TODOs, blind excepts, complexity and nesting, boolean positional arguments, prints; import-linter contracts for a pure domain and application and for one owner per SDK; `react/exhaustive-deps` and the `suspicious` category in oxlint. Every suppression states its reason after a dash.
- `make mutation` runs `mutmut` over the domain in a Linux container (it needs `fork`), with the domain and use case tests. It is run by hand; it becomes a gate once its survivors are triaged.

## Consequences

- The agent cannot present, commit or stop on code that fails a static check, and nobody but the owner can merge a red pull request. A merge on red is visible in the pull request.
- A rule added to `AGENTS.md` that a tool can enforce should be added to the tool in the same change.
- Each SDK has one owner: `migrate` and `migrations` for alembic, the `http` package for fastapi, `openf1` for httpx2, `clean_store` for psycopg, `settings` for pydantic-settings, `raw_store` for pymongo, `replay_store` for redis. Other adapters ask the owner for a client (`mongo_client`, `openf1_http`, `connection_pool`, `redis_client`). Pydantic is the boundary validation library and may be used by any adapter, never by the domain or the application.
- The hooks need Git Bash on Windows and `make` on the path, as the rest of the Makefile already does.
- `make mutation` takes about three minutes and Docker.
