# 2026-11-15 · 01. Pit loss and request tracing

**Goal:** start phase 5 with the two things the simulator needs before its endpoint: each race's pit loss, and failures traceable to their origin.

Reconstructed in the session of 2026-11-16 from the commits, the PR descriptions and the ADRs; the chat of this session was not available.

## What happened

1. The pit loss: measured per race on its own stops and stored with the calibration ([ADR 0015](../adr/0015-pit-loss-from-neighbouring-laps.md), PR #20).
2. The author asked that a failure be easy to trace to its origin before the simulator adds an endpoint that computes on arbitrary input; no failure had prompted it. The agent drafted [ADR 0016](../adr/0016-request-tracing-and-edge-limits.md) and built its backend half (PR #21): one request id through the logs, the responses and the errors; one error shape with a closed code; JSON logs; a readiness check. The agent proposed leaving the nginx half for the next PR.

## Decisions

- **Pit loss from the driver's neighbouring laps**, the median per race, kept but marked not reliable under 5 stops: [ADR 0015](../adr/0015-pit-loss-from-neighbouring-laps.md).
- **A request id, one error shape, JSON logs and limits at the edge, with the standard library**; metrics and traces wait for phase 7: [ADR 0016](../adr/0016-request-tracing-and-edge-limits.md).

## Corrections and redirections

- The first pit loss method measured stops against the lap-time model. It left Montreal, Silverstone and Interlagos with too few usable stops, since their stops fell under the safety car or in the rain, so the neighbour method replaced it. `pit.lane_duration` was rejected as a source: its median is 2369 s in Monte Carlo, where it counts the red flag.
- Mutation testing of PR #20 left 3 boundary survivors in `pit_loss.py`; two new tests kill them.
- The first CI run of PR #21 failed a replay screen test this PR did not touch: the test asserted the stream before the effect that opens it had run. The test now waits for the stream; the app code is unchanged.

## Verification

- PR #20: `make check` exit 0 (601 backend tests, 100% branch coverage); `make mutation` 0 survived; sabotage of the neighbour rule turned the expected tests red; `make calibrate YEAR=2024` twice gave 24 calibrated, then 24 unchanged.
- PR #21: `make check` exit 0 (635 backend tests, 107 frontend); sabotage of the header turned 6 tracing tests red. On the local stack, the same id appeared in the header, the body and the log, and stopping Redis made `/api/health/ready` answer 503.

## Next

- The nginx half of ADR 0016, then the simulator.
