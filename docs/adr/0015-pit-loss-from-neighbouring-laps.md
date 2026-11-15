# 0015. Pit loss is measured per race against the driver's neighbouring laps

- Status: Accepted
- Date: 2026-11-15

## Context

The simulator (phase 5) adds the time a pit stop costs to a strategy's predicted laps. ADR 0014 left that cost out of the lap-time model and gave the decision to phase 5. `AGENTS.md` makes the domain model the owner of every strategy number, so the cost has to be measured from the clean rows, not typed in.

Facts from the 2024 clean model, measured with read-only queries and scratch scripts over the local database on 2026-11-15:

- 825 pit rows in the 24 Race sessions. In all 825, a stint of that driver ends on the pit's `lap_number` and the next lap is flagged `is_pit_out_lap`. In 159 of them the next stint also starts on that lap, the shared boundary of ADR 0008. So lap `n` of a pit is the in-lap on the old tyre, and lap `n + 1` is the out-lap.
- `pit.lane_duration` is not a loss. Its race median is 2369.3 s in Monte Carlo 9523, where it counts cars parked in the pit lane under the red flag, and 59.0 s in Interlagos 9636. Elsewhere it differs from the measured loss below by up to 4.5 s (Silverstone 9558: 29.3 s against 24.8 s).
- First method: (in-lap + out-lap) minus the lap-time model's prediction of both laps, using only stops that are not neutralised and have no slick lap in rain. It leaves Montreal 9531 with 0 usable stops, Silverstone 9558 with 3 and Interlagos 9636 with 2. Those three races ran in changing conditions: their stops fall under the safety car or in the rain, where the model does not predict slick laps.
- Second method: (in-lap + out-lap) minus (the lap before + the lap after the out-lap) of the same driver. The neighbouring laps share the stop's weather and track state, so rain does not exclude a stop. It uses 603 of the 825 stops (80 of them in rain). It leaves 1 usable stop in Interlagos 9636 and 5 to 43 in every other race.
- In the 21 races where both methods have at least 5 stops, their medians differ by less than 0.8 s in 20 and by 1.36 s in Las Vegas 9644.
- The second method's race medians run from 19.17 s (Spa 9574) to 29.51 s (Singapore 9606), so a single season-wide value would miss some circuits by about 7 s.
- Stops excluded by the second method: 110 neutralised, 63 next to another stop of the same driver, 41 whose lap before is lap 1 (the red-flag restarts of Suzuka 9496 and Monte Carlo 9523 account for 34), 4 with a lap missing and 4 with a lap without a duration or a start instant.
- The races with the fewest usable stops have the widest spread: Jeddah 9480 (5 stops, interquartile range 20.66 to 35.15 s), Lusail 9655 (6, 24.57 to 32.33 s) and Monte Carlo 9523 (7, 19.99 to 25.12 s).
- Only the 2024 season is loaded. 2023 or 2025 would take a full ingestion each, and pooling a circuit across years is a new decision under ADR 0014.

## Options

1. **The model method only.** Consistent with the laps the model excludes. Leaves 3 of 24 races unable to simulate a stop.
2. **The neighbour method.** Needs no model, works in rain, and agrees with the model method where both apply. Measures one stop in Interlagos.
3. **A season-wide median for races without enough stops.** Every race gets a value, but it can miss a circuit by about 7 s.
4. **The same circuit in another season.** Most likely right, but costs an ingestion per season and opens cross-year pooling.

## Decision

Option 2. A race's pit loss is the median, over its usable stops, of `(in-lap + out-lap) - (lap before + lap after)` for the same driver, rounded to 0.001 s. A race with fewer than 5 usable stops still gets its value, marked as not reliable.

## Consequences

- A stop is usable unless one named reason excludes it, checked in this order:
  1. its lap before is lap 1 (lap `n` is 2 or less);
  2. one of the four laps is missing;
  3. one of the four has no duration or no start instant;
  4. the stop is next to another stop of the same driver (laps `n - 2`, `n - 1`, `n + 1` or `n + 2` are pit laps, or lap `n - 1` is an out-lap);
  5. one of the four laps overlaps a neutralisation window (as in ADR 0014).
- Rain does not exclude a stop. The neighbour laps run in the same rain, and so do the predicted laps the loss is added to.
- The pit loss is part of a race's calibration. It is computed in the same sweep, stored with it and replaced with it. `CALIBRATION_VERSION` goes to "2", so `make calibrate` recomputes every race once. The lap-time coefficients do not change.
- `MIN_RELIABLE_PIT_STOPS = 5` is part of the version. With 1 to 4 usable stops, the race is calibrated and its pit loss is stored as not reliable, with its stop count. The simulator says so next to every strategy that stops. In 2024 that is Interlagos 9636 alone.
- With no usable stop, the race keeps its lap-time calibration and has no pit loss. The simulator rejects any strategy that stops in that race and names the reason. No 2024 race is in this case.
- The count of stops per exclusion reason is stored, as ADR 0014 does for laps.
- The simulator adds the pit loss once per stop, on top of the model's prediction of the in-lap and the out-lap. The two methods agree on the 2024 races (within 0.8 s in 20 of 21), which supports adding a neighbour-measured loss to model-predicted laps.
- The loss includes what a stop costs on average in that race: the stationary time, penalties served at the stop and slow stops. The median keeps rare slow stops from moving it.
- A stop to or from a different compound includes the change in pace between the old and the new tyre across the neighbour laps. The median over a race's stops averages it out; in a race of stops from slicks to intermediates it does not, and the value carries that.
- A season-wide value and other seasons stay out. A cross-year value per circuit needs its own ADR once a second season is loaded.
