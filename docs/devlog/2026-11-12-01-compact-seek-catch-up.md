# 2026-11-12 · 01. Compact a seek's catch-up

**Goal:** a seek to the last lap of a race shows on screen in a couple of seconds, with the same screen as folding every event (issue #14).

## What happened

1. The author asked for the next step; the agent named phase 4 and the open issues, recommending phase 4. The author chose to close issue #14 first.
2. The agent measured the catch-up size over the 60 loaded sessions (psql) for three rules and asked which events a catch-up keeps.
3. Built on `feat/compact-seek-catch-up` by layer, with [ADR 0013](../adr/0013-a-seek-sends-what-is-still-current.md).

## Decisions

- **A seek sends at once only the events still current at its lap**, written in the seek's own transaction at their timeline ids: [ADR 0013](../adr/0013-a-seek-sends-what-is-still-current.md).

## Corrections and redirections

- The agent offered three rules: every lap whole (up to 1,977 events), the latest lap per driver (up to 704), or only what the screen shows today (about 209). It recommended the latest lap per driver; the author chose it.
- Mutation testing found a surviving mutant: deleting the default `case _: return None` in the key function changed nothing. The agent made a record its own key instead of `None`, so the branch matters; the rerun had none surviving.
- The fresh-eyes audit returned ACCEPT-WITH-FIXES (a stream docstring still describing the old catch-up, a garbled docstring, two ADR numbers without the right source, the event encoding in two places); fixed. Not changed: a property oracle close to the implementation (classification is pinned by example tests) and no code bound on the seek's transaction size (stated in ADR 0013).

## Verification

- `make check`: exit 0. Backend 470 tests at 100% branch coverage; frontend 105 tests at 99.49% branches; OpenAPI contract matches.
- `make mutation`: 1,550 of 1,552 killed, 0 survived, 2 timeouts (the same as before).
- Sabotage: keeping every event, treating weather as a record, cutting with `bisect_left`, and dropping the catch-up in the store each turned the expected tests red; restored.
- Browser, 9472, paused, seek to lap 57: the screen settles in 0.6 to 0.7 s (four runs) against 9.1 and 10.2 s on `main` (two runs), and its text is identical on both.
- Local stack: the stream holds 705 entries and 127 KB after the seek; laps 30 and 1 keep 544 and 45; lap 99 answers 404; the producer appends from `1-31695` on; a `Last-Event-ID` in an id gap resumes at the next entry; no error in the backend log. After the audit fixes the browser rerun was not done (the browser tool hung); the API check was repeated.

## Next

- Phase 4: the predictive engine, planned in the session that starts it.
