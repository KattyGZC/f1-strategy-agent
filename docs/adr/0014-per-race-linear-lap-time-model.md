# 0014. Lap time is a per-race linear model calibrated on clean laps

- Status: Accepted
- Date: 2026-11-12

## Context

Phase 4 builds the model the simulator (phase 5) and the assistant (phase 6) read: given a race, a compound, a tyre age and a lap, the expected lap time. `AGENTS.md` makes the domain model the owner of every lap time or degradation prediction.

Facts from the 2024 clean model, measured with read-only queries and a scratch script over the local database on 2026-11-12:

- 24 Race sessions (`session_key` 9472 to 9662) and 6 Sprints. In 5 of the 6 Sprints no more than 2 of 20 drivers ran a second stint, so their degradation cannot be told apart from race progress.
- No fuel data: no column of the clean model holds fuel, mass or throttle, and car telemetry has no clean table (ADR 0007).
- Within a stint, tyre age and lap number grow together (age = age at start + lap - lap start), so degradation and race progress separate only across stints. A dry race has at least two compounds per finisher.
- `race_control` rows of category SafetyCar carry no flag. Their messages in the 24 races are a closed set: SAFETY CAR DEPLOYED (13), SAFETY CAR IN THIS LAP (12), VIRTUAL SAFETY CAR DEPLOYED (9), VIRTUAL SAFETY CAR ENDING (5), SAFETY CAR THROUGH THE PIT LANE (1). Track-scope flags are GREEN (47), CHEQUERED (24), CLEAR (22) and RED (3). Its `lap_number` is the leader's lap (inferred: it does not follow the lapped cars' laps).
- Rain: `weather.rainfall` is a boolean read about once a minute, with no intensity or track wetness. Inside the race window it is true in Montreal 9531 (30 readings), Silverstone 9558 (37), Interlagos 9636 (95) and Catalunya 9539 (1). INTERMEDIATE was run in those three wet races (37, 23 and 49 stints, 19 or 20 drivers each); WET in 7 stints in total.
- After the last wet reading in Montreal, the median slick lap is 1.307 times the dry reference 5 to 10 minutes later, 1.092 at 10 to 15, 1.041 at 15 to 20 and 1.031 at 20 to 25, where race progress explains the rest. The one wet reading in Catalunya leaves slick laps unchanged.
- After the structural exclusions below, the ratio of a lap to its race's median is 1.020 at p90, 1.057 at p98 and 1.110 at p99; 404 laps of about 26,000 exceed 1.07.
- On 648 dry stints with at least 16 clean laps, the slope of the second half exceeds the first in 373 (58 %); the median difference is 0.016 s per lap.
- Track temperature varies 1 to 12 °C within a race (Silverstone 20.7 to 33.0 under rain, most others under 6) and is confounded with the circuit across races, with one race per circuit in 2024.
- Clean laps per race: HARD at least 32 in 23 races, MEDIUM at least 148 in 22, SOFT under 40 in 13 of its 21 races.

## Options

1. **One model per race and compound, fitted on that race's clean laps.** Keeps what makes a circuit different; a race fits only from its own laps, so a scarce compound may not calibrate.
2. **One season model with an offset per circuit.** More laps per coefficient, but degradation is shared across circuits that wear tyres very differently.
3. **A published fuel effect plus fitted degradation.** Enables a starting-fuel input, but the main coefficient would not come from our data.

## Decision

Option 1. For a Race session, compound `c`, driver `d`, tyre age `a` and lap `l`:

`lap_time_s = base_s[c] + pace_offset_s[d] + degradation_s_per_lap[c] * a + progress_s_per_lap[c] * (l - 1)`

SOFT, MEDIUM and HARD share one progress slope (fuel burn and track evolution together); INTERMEDIATE has its own, since the track dries while it runs. Driver offsets are fixed effects, removed by demeaning each driver's laps, and average zero, so the base is the average car of the race. The fit is exact least squares in rational arithmetic, in pure Python, on clean laps only.

## Consequences

- A lap is clean unless one named reason excludes it, checked in this order: no duration, no stint, compound not calibrated (WET, UNKNOWN), lap 1, pit-out lap, pit-in lap, no start instant, neutralised, restart lap, wet track, outlier, compound with fewer than 30 clean laps, driver with fewer than 10.
- Neutralised: the lap's time interval overlaps a window that opens on SAFETY CAR DEPLOYED, VIRTUAL SAFETY CAR DEPLOYED or a RED flag and closes on the next Track-scope CLEAR or GREEN; a window still open runs to the end of the race. Overlap is of two intervals on one clock, without a tolerance, not the nearest-row join that `AGENTS.md` forbids; lap numbers are not used because race control counts the leader's laps. Every SafetyCar message is checked against the measured set, and one outside it fails that race's calibration, so new wording is never read as racing.
- Restart lap: the lap after a neutralised one, on cold tyres behind the safety car's exit.
- Wet track: a SOFT, MEDIUM or HARD lap overlapping a run of rainy readings or the 20 minutes after its last one; 20 minutes is where Montreal's slick laps return to race pace. INTERMEDIATE laps are not excluded by rain.
- Outlier: a lap more than 1.07 times the median of the laps on the same compound that passed the earlier rules. The median is per compound because in a wet race the intermediate base is 7 % (Montreal) to 22 % (Silverstone) above the slick one.
- The minimums of 30 clean laps per compound and 10 per driver barely move the error: over the held-out stints below, the dry p90 is 0.82 s at 20 per compound and 0.80 s at 30 or 40, and 0.83, 0.80 and 0.79 s at 5, 10 and 15 per driver.
- Degradation is linear in tyre age. A quadratic term is not justified by 58 % of long stints; the tyre cliff is not modelled, and a prediction outside the calibrated tyre ages is flagged as extrapolated.
- On intermediates the fitted degradation runs from -0.18 to +0.34 s per lap across the three wet races: drying and wear both move with the laps an intermediate runs, and one season cannot separate them. Its prediction is still within the tolerance below; its per-compound residual error is kept so the simulator can show it as less certain.
- Not calibrated in phase 4, and the simulator must say so: starting fuel, wind, driver aggressiveness, the WET compound and Sprints. Track temperature is recorded per race (minimum, median and maximum over the readings between the first and last clean lap start), not fitted; a temperature effect needs several seasons of the same circuit and its own ADR. Pit-lane time loss is not part of this model; phase 5 decides it.
- A race whose clean laps cannot determine the coefficients (no clean lap, or tyre age that always moves with the lap) is not calibrated, with the reason and the count of laps per exclusion reason.
- Calibration is a pure function of a race's clean rows and `CALIBRATION_VERSION`; thresholds are part of the version. Later seasons add calibrations under their own session keys; pooling the same circuit across years is a new decision, since the 2026 regulations changed the cars.
- Golden cases: a race winner's last stint with at least 10 clean laps is held out, the race is calibrated without it, and the stint is predicted with the winner's pace. Over every eligible 2024 stint (378, of which 23 on intermediates; 72 more were not eligible because the driver or the compound had no other clean laps), the mean absolute error is 0.46 s at p50 and 0.80 s at p90 on dry compounds, and 0.87 s at p50 and 1.18 s at p90 on intermediates. The tolerances are 0.8 s dry and 1.2 s on intermediates; the cases are Bahrain 9472, Catalunya 9539 and Montreal 9531 (dry stints of driver 1) and Silverstone 9558 (driver 1 on intermediates).
- Calibration of the 2024 races takes about 0.1 s each on a laptop.
