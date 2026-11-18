# 2026-11-16 · 01. Edge limits and strategy simulation

**Goal:** finish ADR 0016 at nginx, and simulate race strategies in the domain.

## What happened

1. The agent read the state of phase 5 and proposed three PRs, with a recommendation for each decision of the simulator. The author took them all.
2. The nginx half of ADR 0016, with `make edge-check` against the running stack, run in CI (PR #22).
3. The agent measured the 2024 calibrations (compounds per race, calibrated tyre ages, the lap 1 offset, rain) and drafted [ADR 0017](../adr/0017-strategy-simulation-in-the-race-it-was-calibrated-on.md). The author accepted it as drafted, and it was built as PR #23: `simulate` in the domain, and each race's rain readings stored with its calibration.
4. The author asked whether the merged PRs are deterministic. The agent reviewed #17 to #22: joins by ids, explicit sort keys, exact arithmetic, and `hypothesis` order properties. The only random values are request ids, on purpose.

## Decisions

- **The simulator accepts only what the model calibrated** (race, driver, stints) and names the rest as not modelled: the standing start, starting fuel, wind, aggressiveness, track temperature, and rain on slicks: [ADR 0017](../adr/0017-strategy-simulation-in-the-race-it-was-calibrated-on.md).
- **A strategy the race cannot run is rejected alone**, with its reason and stint, next to the ones that simulated.

## Corrections and redirections

- The agent opened by calling the nginx half of ADR 0016 never implemented. PR #21 had named it as the next PR.
- The agent first split the nginx config into snippets, then went back to one file, so that the path ADR 0016 names stays true.
- The first CI run of PR #22 failed: the runner's curl 7.81 lacks `%header{}`. Each burst request now writes its headers to a file; checked in an Ubuntu 22.04 container before the push.
- The ADR 0017 draft counted rain between the first and last clean lap. A test showed that rain excludes the slick laps around it, so that window misses rain at either end. Rain is now counted over the whole race, and the ADR was corrected before its merge.
- The first `make mutation` reported 142 "no tests" mutants: the new test file was not in mutmut's selection. After adding it, two survivors were left: an equivalent `<=` (the code was rewritten) and an untested error message (now tested).
- Migration 0005 deletes the version 2 calibrations, so the new column is `NOT NULL` from the start. The agent flagged this as its reading of the rule against dropping data (the calibrations are derived and `make calibrate` rebuilds them); the author accepted that reading and merged it.

## Verification

- PR #22: `make edge-check` passed. With the phase 0 config it gives 31 failures; restored with `git restore` and `cp`. CI green after the curl fix.
- PR #23: `make check` exit 0 (666 backend tests, 100% branch coverage); `make mutation` 2389 killed, 0 survived. Sabotage of the stop and of the rain window turned 4 tests red each. `make calibrate YEAR=2024` gave 24 calibrated, then 24 unchanged; rain readings 97, 37, 27 and 1, pinned as golden cases.

## Next

- PR B2: read the stored calibration, `GET /api/races`, `GET /api/races/{session_key}` and `POST /api/simulations`, and the nginx zone of the simulator.
