# 0013. A seek sends at once only the events still current at its lap

- Status: Accepted
- Date: 2026-11-12

## Context

A seek to lap N sends the session from its start up to the earliest start of lap N without pacing, then paced events (ADR 0009, ADR 0012). For lap 57 of the 2024 Bahrain race (`session_key` 9472) that is 31,717 events (ADR 0012), most of them intervals: 29,844 of the race's 32,493 events are. Chromium's `EventSource` took 6.7 s to receive the 31,701 it was sent, and the screen showed lap 57 about 9 s after the click (ADR 0012, issue #14).

The screen keeps, of every event, the latest position, interval, lap and pit of each driver, the latest weather, and every race control message (`frontend/src/replay/fold.ts`). Overtakes and team radio do not change it yet.

Measured over the 60 sessions in the clean model, a seek to the last lap (psql, 2026-11-12):

- Every event up to it: up to 32,753 events.
- Records whole (laps, pits, race control, overtakes, team radio), and the latest position and interval of each driver and the latest weather: up to 1,977, 896 on average.
- The same, but only the latest lap of each driver: up to 704.

## Options

1. **Send every event, as today.** The rebuilt screen is exact by construction; the browser is slow to take it in.
2. **Send what the screen keeps today.** At most about 209 events (the same psql query), but the stream then carries what one screen happens to show, and the next panel that lists overtakes or radio would need this decision again.
3. **Send what is still current at the lap.** An event that states a value that a later event replaces (a driver's position, interval or last lap, the weather) is sent only if no later event before the lap replaces it; every other event (race control, pits, overtakes, team radio) is a record and is sent whole.

Where the catch-up is written:

1. **By the producer, in batches of `REPLAY_APPEND_BATCH`.** The state would carry where the catch-up ends, and the append would take ids with gaps.
2. **By the seek, in its transaction, after the reset.** The seek already builds the timeline to find the lap; the producer goes on from the last id as it does after any restart.

## Decision

Option 3, written by the seek. The events a seek sends at once are a pure function of the timeline and the lap's session time (`catch_up` in `domain/playback.py`, from `still_current` in `domain/replay.py`); the store writes them after the reset in the seek's transaction, each at its own id `<generation>-<n>`, and the producer appends from the next event of the timeline.

## Consequences

- This changes what ADR 0009 and ADR 0012 say about a seek: the stream after a reset holds the events still current at the lap, not every event up to it. Everything else in those decisions holds.
- The screen rebuilt from the catch-up equals the one rebuilt from every event: identical text after a seek to lap 57 of 9472, on this change and on the one before it (browser, 2026-11-12). A `hypothesis` property in `tests/test_domain_replay.py` states the rule; a test in `frontend/src/replay/fold.test.ts` folds both and compares them.
- The last event up to the lap is always sent, since no later one replaces it, so the stream's last id is the count of events up to the lap and the producer's next append follows it exactly (a `hypothesis` property in `tests/test_domain_playback.py`).
- Ids within a generation now have gaps after its reset. They still only grow, so `Last-Event-ID` resumes at the next entry, also from an id in a gap.
- A seek to lap 57 of 9472 writes 704 events: the stream holds 705 entries and 127 KB, against 31,718 and 6.0 MB before (`XLEN`, `MEMORY USAGE`). The screen settles 0.6 to 0.7 s after the click in four runs, against 9.1 and 10.2 s in two runs before it (Chromium, 2026-11-12). The seek answers in about 0.5 s, as before.
- One seek writes up to 704 events in one transaction in the loaded data, under `REPLAY_APPEND_BATCH` (2,000): a season with longer races or more overtakes would need this measured again.
- Choosing the catch-up costs about 28 ms of CPU for the last lap of a race; it runs in a thread, as building the timeline does.
- A future panel that needs the history of a value (every lap of a driver, a lap chart) reads it from the clean model through the API, not from the replay stream.
