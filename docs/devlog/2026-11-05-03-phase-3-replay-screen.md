# 2026-11-05 · 03. Phase 3: replay screen

**Goal:** the browser lists the loaded sessions and replays one with its timing tower, weather, race control and controls.

## What happened

1. The author asked for the next step. The agent proposed killing the surviving domain mutants; the author redirected (see Corrections), so the plan became the replay screen the phase 3 entry had left next, with seek in its own PR.
2. Backend: a session catalog use case and its PostgreSQL adapter, `GET /api/sessions` and `GET /api/sessions/{session_key}`. Frontend: a pure fold of replay events, an SSE watcher, the screen.
3. A fresh-eyes audit returned ACCEPT-WITH-FIXES; 14 of 15 findings were fixed. The fifteenth, stopping a replay when the viewer leaves it, needs an endpoint and stays out of this PR.
4. The author found the first screen confusing and shared screenshots and a racing game's interface as a reference. The agent drew a two-screen mockup, the author settled language, the reserved strategy space and the accent, and the agent rebuilt the screen on it.

## Decisions

- **Thin read models** (`LoadedSession`, `SessionDriver`) instead of the clean records, so the query selects only the shown columns; sessions carry `meeting_key` so the picker groups them by id.
- **The screen shows only values that came in events** (ADR 0009). An event counter the frontend computed was removed after the audit; a fastest-lap highlight was left out of the redesign for the same reason. The track flag is the flag of the latest race control message about the whole track; a safety car arrives only as message text and is not shown.
- **One render per animation frame**: events that arrive within a frame are folded together.
- **No nginx change**: FastAPI already sends `X-Accel-Buffering: no`; a test asserts it.
- **No official logo**: a trademark, and the project ends in a public demo. A footer says the project is not affiliated.
- **The circuit map** will be traced from OpenF1 location data and kept in the clean model, in its own PR with an ADR. The screen keeps its place.
- **English interface**; a Spanish option is for a later version. The strategy tools show, disabled, where they will go.

## Corrections and redirections

- The agent proposed the surviving mutants as the next step. The author said they were already being handled in another conversation, and later that `main` had them (PR 10).
- The first screen was a plain table and two selects. The author: "nothing makes me think this is about F1, there is no context" (translated). The redesign followed.
- The agent first read 0 fps as the page saturating with one render per event. The browser page was hidden, so no frames ran. Batching stayed, measured at 60 fps; the per-event version was not measured cleanly.
- A global pytest plugin for the API fixtures broke `make mutation` (its sandbox does not copy adapters); the fixtures moved to `tests/http/conftest.py`.

## Verification

- `make check`: exit 0. Backend 417 tests at 100% branch coverage; frontend 84 tests at 99.4% branches; OpenAPI contract unchanged.
- `make mutation`: exit 0, 1,497 killed, 0 survived, 2 timeouts (before the redesign; the domain did not change after).
- Sabotage: the session tie-break and the gap unit preference each went red and were restored.
- Browser on the local stack: the 2024 Bahrain race at 60x; picker, tower, driver card, pause, resume and speed checked. SSE through nginx arrives every second.

## Next

- Seek to a lap (ADR 0009), the last PR of phase 3.
- The circuit map from OpenF1 location data, with its ADR.
