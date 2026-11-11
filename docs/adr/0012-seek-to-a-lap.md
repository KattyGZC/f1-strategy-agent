# 0012. A seek replaces the replay's stream with a new generation

- Status: Accepted
- Date: 2026-11-10

## Context

ADR 0009 lets a viewer jump to lap N: a new generation starts at the earliest `date_start` of lap N, the stream gets a reset, then the timeline from the start up to that instant without pacing, then paced events. It leaves open what happens to the generation the seek leaves, which laps can be sought, and what keeps producing after the timeline ends.

Facts that shaped the answers:

- A replay's stream is what sizes Redis: 6.2 MB for the 2024 Bahrain race (ADR 0009). Keeping every generation would grow a replay by up to that much per seek.
- Lap 1 often has a start and no duration: 547 such laps in the loaded data, and 51 laps have no `date_start` at all; every lap number of every loaded session has at least one driver with a start (psql, 2026-11-10).
- Before this change a producer returned at the end of the timeline and released its lease. A seek back after the end, or one landing while the producer was returning, would have found no producer, in this process or another.
- One append of a whole late-lap catch-up (31,717 events, lap 57 of 9472) blocked Redis for 91 to 126 ms, measured with `SLOWLOG` while the mutation tests ran on the same machine (2026-11-10).

## Options

The generation a seek leaves:

1. **Keep it in the stream.** Old ids stay readable; memory grows with every seek and nothing bounds it.
2. **Replace the stream.** One generation at a time, so the memory bound of ADR 0009 holds. A viewer whose `Last-Event-ID` is of an old generation still reads the reset first, since `<g>-0` is greater than every id before it.

What produces after the end of the timeline:

1. **The producer returns, and a seek starts one again.** A seek racing a returning producer, or one whose producer lease is held in another process, is lost.
2. **The producer keeps ticking until the replay is gone.** One state read and one lease renewal per tick, bounded by the number of active replays.

## Decision

A seek replaces the stream, in one WATCH transaction, with the new generation's reset (`<g>-0`, carrying the lap number and its session time) and keeps the replay's expiry; the timeline follows as `<g>-1`, `<g>-2`. An append names its generation and appends nothing to a newer one. A producer runs until its replay is gone, and appends at most `REPLAY_APPEND_BATCH` events at a time.

## Consequences

- The lap a seek goes to is the earliest `date_start` of that lap number among the session's laps, with or without a duration, as a pure function of the timeline. A lap no driver has a start for answers 404, and the replay does not change. The session's last lap number comes with the session (`GET /api/sessions/{session_key}`), so the screen offers only laps that exist.
- The catch-up up to the lap needs no path of its own: the playback is anchored at the lap's session time, and every event up to it is due at once (a `hypothesis` property in `tests/test_domain_playback.py`). A paused replay stays paused, at the lap; the speed is kept.
- After a seek the stream holds one generation: 31,718 entries and 6.0 MB after a seek to lap 57 of 9472, 113 after a seek to lap 1. A second seek drops the first.
- An append that a seek superseded writes nothing; the producer reads the new generation on its next tick and appends it from the start. A seek of a replay that expires while its timeline is built answers 404 and writes nothing.
- A seek starts a producer for a replay whose process died, as a watch does.
- A failed replay cannot be sought (409): its producer would not produce it again (ADR 0009), and its viewers already received the failure.
- The stored state now carries the generation; a replay stored before this change does not decode. Replays expire after five idle minutes and nothing is deployed yet, so none survives an upgrade.
- With `REPLAY_APPEND_BATCH=2000`, a seek to lap 57 of 9472 makes 16 appends of at most 4.7 to 5.9 ms each, and the seek answers in about 0.5 s (idle machine, 2026-11-10). Building the timeline for the seek costs what it costs the producer (ADR 0009).
- The browser is now the slow end of a seek to a late lap: Chromium's `EventSource` received the 31,701 catch-up events of lap 57 in 6.7 s, where `curl` through the same nginx took 1.3 s, so the screen shows lap 57 about 9 s after the click. Sending less than every event in the catch-up changes what a replay's content is (ADR 0009) and is a separate decision.
- A finished replay costs one state read and one lease renewal per tick until it expires or is stopped.
