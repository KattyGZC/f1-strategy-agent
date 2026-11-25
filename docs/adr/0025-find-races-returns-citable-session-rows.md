# 0025. `find_races` returns citable `session` rows

- Status: Accepted
- Date: 2026-11-25

## Context

ADR 0021 says every data tool returns its rows as `search_result` blocks with citations enabled, each with a source id `row:<table>:<session_key>:<key...>`. ADR 0023 lists `find_races` as a data tool that returns races of the clean model (`session_key`, name, date, whether calibrated), but the closed set of a `row` source's `table` (`session_result`, `starting_grid`, `stint`, `pit`, `lap`, `race_control`, `weather`) has no value for a race itself. Building `find_races` in T2 of the phase 6 plan made the two ADRs disagree.

## Options

1. **Add `session` to the row tables.** Each race `find_races` returns is a `row` source keyed by its `session_key` alone (`row:session:9472`), whose values are the session's name and start, the circuit, the country and whether it is calibrated. It keeps ADR 0021's rule for every data tool, and a race's date in an answer can be cited.
2. **Return `find_races` as plain text, not citable.** No change to the row tables, but a new kind of tool result, an exception to ADR 0021, and a race's date in an answer with nothing to cite.

## Decision

Option 1, chosen by the author on 2026-11-25. It supersedes the list of row tables in ADR 0023, which gains `session`. The rest of ADR 0023 stands.

## Consequences

- `RowTable` gains `session`. A row whose table's primary key is `session_key` alone has an id without a key part: `row:session:<session_key>`.
- The tab's citation panel shows a `session` row like any other row (T5).
- `find_races` lists only sessions of type Race (the Grand Prix and the Sprint), with `session_name` telling them apart.
