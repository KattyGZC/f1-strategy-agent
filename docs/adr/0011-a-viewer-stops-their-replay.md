# 0011. A viewer stops their replay

- Status: Accepted
- Date: 2026-11-10

## Context

ADR 0009 gives each viewer their own replay, bounds the number of active replays (`REPLAY_MAX_ACTIVE`, 10 by default) and expires a replay nobody reads for `REPLAY_IDLE_TTL_S` (300 s by default). Nothing else ends a replay. The replay screen lets a viewer leave a replay for another session, so every switch left a replay holding its place for up to five minutes, and a few switches in a row could reach the limit and refuse the next start with a 503.

A producer appends to its replay's stream between reads of its state. Before this decision an append to a replay that was gone failed with a Redis error, and the producer ended as failed.

## Options

1. **Wait for the idle expiry.** Nothing to build; leaving keeps a place taken for minutes.
2. **A shorter idle expiry.** Frees places sooner, but a paused or briefly disconnected viewer loses their replay.
3. **A stop the viewer asks for.** One route and one store operation; the place is free at once.
4. **Stop on closing the tab** (a `keepalive` request on `pagehide`). The browser does not promise to send it, and a reload would stop a replay the viewer meant to keep.

## Decision

`DELETE /api/replays/{replay_id}` removes the replay, its stream and its producer lease and frees its place, in one Redis script. The screen calls it when the viewer chooses another session; closing the tab still leaves the replay to its idle expiry.

## Consequences

- A stop and an expiry look the same to everyone else: the producer finds the replay gone and ends as expired, and a viewer's stream ends. An append to a gone replay now returns that it appended nothing instead of failing.
- Whoever knows a replay's id can stop it, as they could already pause it; the id is unguessable (ADR 0009).
- Stopping a replay that is already gone answers 404; the screen takes that as stopped. Any other failure is shown, and the replay is left to its idle expiry.
- The idle expiry and the limit stay as ADR 0009 sets them.
