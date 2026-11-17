# 0017. A strategy is simulated in the race it was calibrated on, from the model alone

- Status: Accepted
- Date: 2026-11-16

## Context

Phase 5 lets a user compare race strategies. `AGENTS.md` lists the inputs the brief asks for (weather, track temperature, wind, tyre compound, pit plan, starting fuel, driver aggressiveness) and makes the domain model the owner of every lap time and strategy outcome. ADR 0014 calibrates, per Race session, a lap time from compound, tyre age, lap and driver, and says the simulator must name what it does not model. ADR 0015 adds a pit loss per race. ADR 0016 bounds a simulation body at 4 strategies of 6 stints.

Facts from the 2024 clean model and its calibrations, measured with read-only queries over the local database on 2026-11-16:

- 24 races are calibrated, of 44 to 78 laps. Each has a pit loss; Interlagos 9636 is the only one marked not reliable (1 stop).
- Calibrated compounds per race: SOFT, MEDIUM and HARD in 11; MEDIUM and HARD in 10; SOFT and HARD in 1; MEDIUM, HARD and INTERMEDIATE in Montreal 9531; MEDIUM and INTERMEDIATE in Silverstone 9558; INTERMEDIATE alone in Interlagos 9636. So a race can only simulate the compounds it calibrated, and in two races no strategy with two dry compounds exists.
- Calibrated tyre ages start at 1 to 5 laps, never 0: a stint's first lap is a pit-out lap or lap 1, and both are excluded (ADR 0014). The highest calibrated age is 15 to 28 laps on SOFT, 16 to 77 on MEDIUM, 29 to 78 on HARD.
- Tyre age at the start of a stint: 0 in 407 of 478 first stints and 687 of 831 later ones; up to 8 on a first stint and 28 on a later one.
- Stints per driver: 1 to 5.
- Lap 1, which the model excludes, is slower than the model's prediction of it by 5.0 to 61.7 s (race median over drivers; 8.3 s across races; the highest is a race neutralised on lap 1). It is the same for every strategy of one race and driver.
- Between the start of a race's first lap and the start of its last, rain readings fell in 4 calibrated races: Interlagos 9636 (97), Silverstone 9558 (37), Montreal 9531 (27) and Catalunya 9539 (1). Spielberg 9550 had one more, before the start. Rain excludes the slick laps around it (ADR 0014), so counting only between the first and last clean lap would miss rain near either end of a race. The model predicts a slick lap at dry pace whatever the weather (ADR 0014 excludes wet slick laps from the fit), and an intermediate lap at its race's average.
- Starting fuel, wind, driver aggressiveness and the effect of track temperature are not in the model (ADR 0014); weather is a property of the race, not of a lap the user can set.

## Options

1. **Accept every input of the brief and adjust the model's lap time by rules of thumb** (a fuel effect per kg, a temperature factor). Matches the brief's list, but the numbers would not come from our data, which `AGENTS.md` forbids.
2. **Accept every input, but simulate only what the model calibrated, and echo the rest as not modelled.** The form looks complete; the inputs change nothing, which reads as a bug.
3. **Accept only what the model calibrated: race, driver and the stints; name the rest as not modelled.** Honest and small; the brief's other inputs wait for a model that can carry them.

## Decision

Option 3. A simulation is a pure function of one race's stored calibration and up to 4 strategies for one driver or the average car. A strategy is its stints in order; the race's own conditions are the weather. Every lap time is `predict_stint` (ADR 0014), every stop adds the race's pit loss (ADR 0015), and what the model does not carry is listed, never adjusted for.

## Consequences

- **Input.** `session_key`, an optional `driver_number` (absent: the average car of the race) and 1 to 4 strategies of 1 to 6 stints. A stint is a compound, a number of laps (at least 1) and the tyre age at its start (0 to 99 laps, a schema bound that fits any race; 0 is a new set). Stint `k` starts on the lap after stint `k - 1` ends; the first starts on lap 1.
- **Rejections, per strategy.** A strategy whose laps do not add up to the race's laps, that runs a compound the race did not calibrate, or that stops in a race without a pit loss, is answered as rejected with one closed reason and the stint it names, next to the strategies that simulated. A whole request is refused when the race is not calibrated (404 `race_not_calibrated`) or the driver is not calibrated in it (404 `driver_not_calibrated`).
- **Stops.** A stop sits between two stints: the in-lap is the last lap of the first, the out-lap the first of the next. Both are predicted as racing laps and the race's pit loss is added once, on the in-lap's stop, as its own line, not folded into a lap time. A stop to the same compound is a stop to a new set of it.
- **Output.** Per simulated strategy: each lap (number, compound, tyre age, lap time, extrapolated), each stop (in-lap, pit loss) and the total race time, all rounded to 0.001 s; and its gap to the fastest simulated strategy. The total is the sum of the laps and the stops.
- **Caveats, a closed set per strategy:** `pit_loss_not_reliable` when it stops in a race whose pit loss is marked so; `extrapolated_tyre_age` when a lap is outside the calibrated tyre ages (every stint's first lap is, at the measured ages, since age 0 is never calibrated); `one_dry_compound` when every stint runs the same dry compound. The last is reported, not rejected: the sporting rules reach the project with the assistant (phase 6), and every finisher of a dry 2024 race ran at least two compounds (ADR 0014).
- **Not modelled, a closed set per race, shown with every result:** the standing start (lap 1 is predicted as a racing lap, so the total is short by the start's cost, the same for every strategy), starting fuel, wind, driver aggressiveness, the effect of track temperature, and, in a race with rain readings, rain on slick tyres. The comparison between strategies of one race is what the simulator answers; the absolute total is not a race result.
- **Rain readings are stored with the calibration**, counted from the start of the race's first lap to the start of its last, of any driver, so the simulator does not read weather rows itself. `CALIBRATION_VERSION` goes to "3"; the coefficients and the pit loss do not change. Migration 0005 deletes the calibrations of version 2, which cannot carry the count, with their runs; the next `make calibrate` rebuilds them, as it would for any new version.
- **Endpoints.** `GET /api/races` lists the calibrated races; `GET /api/races/{session_key}` gives one race's laps, calibrated compounds with their tyre ages and residual error, calibrated drivers, pit loss and its reliability, track temperature, rain readings and what is not modelled, so the screen builds its form from the API; `POST /api/simulations` simulates. Nothing is stored: a simulation is recomputed from the calibration on every request. It is pure arithmetic on at most 4 strategies of 78 laps, so it runs in the request.
- **Edge.** `/api/simulations` gets its own `limit_req` zone in `frontend/nginx.conf`, tighter than the API's (ADR 0016): 5 requests per second per address with a burst of 10.
- **Reproducible.** The same calibration and strategies give the same result, and a strategy's result does not depend on the other strategies in the request except for its gap to the fastest; both are `hypothesis` properties.
- **Later inputs.** Starting fuel, temperature or weather as inputs need a model that carries them, from several seasons of the same circuit, and their own ADR. Until then the screen lists them as not modelled.
