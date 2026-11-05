# 2026-11-05 · 02. Domain mutants

**Goal:** every domain mutant is killed by a test through the public function, and `make mutation` fails when one survives.

## What happened

1. After PR 9 merged, the author asked to finish what was left in a new PR: the 60 domain mutants no test killed.
2. The agent read each survivor's diff. Most were real gaps: fields no test asserted (`stop_duration`, `driver_number`, `rainfall`, laps behind), error messages that lost their field or endpoint, boundaries (a stint's last lap, a session ending at the cutoff), a fingerprint format nothing pinned. A few could not change behavior.
3. 34 tests through `clean_session`, `timeline`, `RawRequest`, `chosen_sessions`, `due_until` and `RetryPolicy`; three equivalent branches removed from the domain. `make mutation` became a gate and a CI job.

## Decisions

- **Equivalent mutants are removed, not excluded**: `to_decimal` uses `repr` for ints too, `_phases` indexes its three phases instead of a `zip(strict=True)` that could never fail, and the phases skip a duplicate check the results already make. No `pragma: no mutate`.
- **The fingerprint format is pinned** like the content hash: it is stored with each load, so a change loads every session again.
- **Mutation runs in a zone that is not UTC** (`TZ=EST5`): in UTC, `astimezone(None)` and `astimezone(UTC)` agree and the mutant hides.
- **The gate is detached and polled** (`infra/mutation.sh`): Docker Desktop on Windows dropped the attached stream of long runs.

## Corrections and redirections

- The agent first made the verdict the container's last printed line, to work around the exit code of `docker run`. The next run showed the stream itself dropping halfway and the container left running; the script now polls the container and reads its exit code.
- A new constant was placed between an existing comment and the constant it explains; caught on audit and moved.

## Verification

- `make mutation`: 1,497 of 1,499 mutants killed, 0 survived, 2 timeouts (a mutant that hangs a test). With the pit test removed: fails, naming `_pit__mutmut_17`.
- `make check`: exit 0, 407 backend tests at 100% branch coverage.

## Next

- Watch the `mutation` job on the PR, then make it a required check on `main`.
