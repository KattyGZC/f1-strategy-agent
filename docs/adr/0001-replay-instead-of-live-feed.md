# 0001. Replay historical sessions instead of consuming the live feed

- Status: Accepted
- Date: 2026-10-26

## Context

The project must show real-time processing: telemetry, intervals, race control messages and weather arriving as a stream, processed without blocking, pushed to the browser.

OpenF1 is the data source. Its site (openf1.org, read 2026-10-26) states that historical data is free, that "Live data during sessions with REST, MQTT, and WebSocket" requires a sponsor plan at €9.90/month, and that the free tier allows "Up to 3 requests per second and 30 requests per minute".

Live sessions happen on roughly 24 weekends a year. A demo that only works during a session cannot be shown to a reviewer on a Tuesday.

## Options

1. **Live feed (paid).** Real data in real time. Costs a subscription, works only during sessions, and cannot be tested repeatably.
2. **Replay of historical sessions.** A producer reads a stored session from our own store and emits its events in timestamp order at 1x or faster, through the same queue and consumers a live feed would use. Free, available any day, deterministic, testable.
3. **Both.** A live adapter behind the same port as the replay producer. Adds a paid dependency before the pipeline exists.

## Decision

Option 2. The stream comes from a replay producer over sessions already ingested. The producer is an adapter behind a port, so a live adapter can be added later without changing the consumers.

## Consequences

- Ingestion is historical only, and must stay under 30 requests per minute on the free tier. The adapter enforces it.
- Replay order is the event timestamp plus an explicit tie-break, never arrival order.
- The same session replayed twice produces the same stream, so the pipeline can be tested end to end.
- The README and the demo say "replay", not "live". Claiming live data would be false.
