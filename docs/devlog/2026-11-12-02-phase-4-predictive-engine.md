# 2026-11-12 · 02. Phase 4 predictive engine

**Goal:** a lap-time and degradation model per race, calibrated on real stints and stored, with golden cases from 2024 races.

## What happened

1. Before planning, the author asked which seasons production will hold, whether the current season updates itself, and whether a race not yet run can be predicted; then what the databases would cost and whether Anthropic covers the assistant. The agent answered from ADR 0006 and 0007 and measured the local clean model (77 MB of PostgreSQL for 2024). The author kept 2024 for phase 4 and left the rest to its phases.
2. The agent proposed four decisions with a recommendation each; the author took all four (per race and compound, one progress slope instead of fuel, wind and aggressiveness out, pure Python least squares) and asked whether later seasons need rework (they do not: calibrations key on `session_key`).
3. The agent measured 2024 (rain, safety car messages, outlier ratios, curvature, track temperature, Sprints) and drafted [ADR 0014](../adr/0014-per-race-linear-lap-time-model.md).
4. Built in three PRs: the tyre lookup extracted from the replay (#17), the domain model with golden cases (#18), and the calibration tables, sweep and `make calibrate` (this branch).

## Decisions

- **A per-race linear lap-time model on clean laps**, thresholds measured on 2024, stored per session and recalibrated when its clean rows or the model change: [ADR 0014](../adr/0014-per-race-linear-lap-time-model.md).
- Sprints and pit-lane loss are out of phase 4 (Sprints cannot separate degradation from progress; pit loss belongs to the simulator).

## Corrections and redirections

- The plan left rain out of the model. The author asked whether there was no rain data; the agent corrected itself (OpenF1 has a per-minute rainfall flag, true in four 2024 races) and offered three options. The author chose to also calibrate intermediates, over the agent's recommendation of excluding only the rainy periods.
- The author asked why there was no self-grade table after the ADR draft: the agent had not implemented anything yet, waiting for the ADR's OK as the plan said.
- Mutation testing of PR 2 left 44 survivors, all equivalent (`zip(strict=...)`, `sum` start values, explicit default rounding) plus two untested boundaries; the agent removed the constructs and added the tests, and the golden hash did not change.
- The audit of PR 2 found that an unknown safety car message inside an open window went unchecked; every message is now checked.
- The author asked whether the agent fixes causes or symptoms. The agent had changed a sync test that used an async fixture to async without proving why it broke; a probe then showed pytest's own error ("requested an async fixture ... with no plugin or hook that handled it"), so the change was the cause. It had also restored a sabotaged file with `mv`, which kept the old file time, so `uv` did not rebuild and one `make check` ran the sabotaged build; `touch` only unblocked that run. The procedure is now to restore with `git restore` or `cp`.

## Verification

- `make check`: exit 0 on each PR; on this branch 570 backend tests at 100% branch coverage, frontend 105 tests, OpenAPI contract matches.
- `make mutation`: 0 survived on each PR (2142 mutants on the last two, 2 timeouts in `openf1.py` as before).
- Sabotage on each PR (newest-stint order, the intermediate slope, the unchanged check) turned the expected tests red; restored.
- Scratch script over the 24 local 2024 races: each calibrates in about 0.1 s; holding out each driver's last stint, MAE is 0.46 s at p50 and 0.80 s at p90 on dry tyres, 1.18 s at p90 on intermediates.
- Local stack: `make migrate`, then `make calibrate YEAR=2024` twice: 24 calibrated, then 24 unchanged; 58 compound fits stored.

## Next

- Phase 5: the simulator API and screen, planned in the session that starts it.
