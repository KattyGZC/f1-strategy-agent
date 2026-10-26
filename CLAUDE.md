# F1 Strategy Agent

Before planning or editing, read `AGENTS.md`. It binds. If code, a plan or an idea contradicts it or an accepted ADR in `docs/adr/`, stop and say so.

- `AGENTS.md`: coding standard, status, owners, and how work is presented.
- `docs/adr/`: decisions the code relies on. Do not reverse one in passing.
- `docs/devlog/`: one entry per session, in order. Read the latest entry to pick up where the last session stopped.

The user speaks Spanish in the chat. Everything committed is in English.

At the end of every implementation, before any commit, run `self-grade` and `tech-audit`. Every applicable row must be **A** and the audit **SHIP**; fix and re-run until they are. At the end of every session, run `devlog`.
