# 2026-11-18 · 01. Phase 5: the simulator API and screen

**Goal:** put the strategy simulator behind the API and give it a screen, closing phase 5.

## What happened

1. The agent planned PR B2 from the 2026-11-16 devlog. The author approved it, and it was built as five commits by layer: the read of a stored calibration, the use cases, `GET /api/races`, `GET /api/races/{session_key}` and `POST /api/simulations`, a tighter nginx zone, the READMEs ([PR #25](https://github.com/KattyGZC/f1-strategy-agent/pull/25), merged).
2. For the screen, the agent asked how screens switch, how charts are drawn and how big the PR is. The author chose what "shows more seniority without over-engineering" (translated): tabs whose screen lives in the URL hash, a hand-drawn SVG chart, one PR that closes the phase ([ADR 0018](../adr/0018-screens-state-and-charts-in-the-frontend.md)).
3. The agent built the Simulator tab and opened [PR #26](https://github.com/KattyGZC/f1-strategy-agent/pull/26). The author reviewed it in the browser and found layout faults, then asked whether `self-grade` and `tech-audit` had run.
4. Both skills were run over the branch. The tech audit, by a subagent that had not written the code, said ACCEPT-WITH-FIXES with 12 findings; the agent's own self-grade found 5. They were fixed in seven commits, each graded, audited and shown before it was made, the last one adding [ADR 0019](../adr/0019-the-edge-says-how-long-a-browser-keeps-each-file.md).

## Decisions

- The simulator reads the stored calibration as it is, whatever its `CALIBRATION_VERSION`; the next `make calibrate` replaces it.
- ADR 0016's list of error codes is not edited: accepted ADRs are not rewritten, and ADR 0017 already names `race_not_calibrated` and `driver_not_calibrated`.
- Results the form has moved on from are dimmed with a notice, not cleared, so they can still be compared.
- The chart has no `viewBox`: laps sit at percentages of its width, times at pixels, the time axis in its own column, so its text keeps one size at every width.
- `index.html` is revalidated on every load, hashed assets are kept for a year, and a missing asset is a 404 instead of `index.html` (ADR 0019).

## Corrections and redirections

- The author's rule is to show the self-grade and tech-audit tables and wait for an OK before each commit. For PR #26 the agent took "go ahead with everything" (translated) as approval for every commit and skipped both skills. The author asked whether they had run; they had not. The fixes that followed went one commit at a time, each with both tables and an OK.
- The first fix for chart text that grew with the screen capped its height. The audit showed the text still shrank between 48rem and about 1056 px; dropping the `viewBox` fixed it at the cause.
- Empty space below the footer came from the chart's screen-reader table: `.visually-hidden` sat on the `<table>`, and a table's height is a minimum (CSS 2.1, 17.5.3), so it stayed 1473 px tall. The table now sits in a hidden `div`. The author read the first explanation as "you removed the footer"; the agent asked what they saw before changing anything else.
- When the footer then went missing on every screen, the agent guessed the Windows taskbar hid it. The author rejected the guess: "do not make conjectures, investigate the real cause" (translated). The measurement showed the browser automation drove the author's own browser, and the agent had emulated a 900 px viewport in a tab whose visible area is 866 px: the footer sat in the 34 px cut off. In a tab without emulation it ended at 866 of 866. Not an app bug; widths are now tested in an isolated browser context.
- The `self-grade` skill loaded another project's version; the agent followed this repo's file.
- Smaller changes from the plan: a race `<select>` instead of 24 cards, no reordering of stints (remove and add do it), and commits reordered so the tabs land after the screen they open.

## Verification

- PR #25: `make check` exit 0 (703 backend tests, 100% branch coverage); `make mutation` 2391 mutants, 2389 killed, 2 timed out in `domain/openf1.py`, 0 survived; `make edge-check` exit 0. Through nginx on the 2024 calibrations, Bahrain gave 5588.697 s for SOFT 18 + HARD 39 and 5571.562 s for SOFT 15 + HARD 21 + HARD 21, and rejected MEDIUM with `compound_not_calibrated`.
- PR #26: `make check` exit 0 (188 frontend tests, 100% lines, 99.42% branches; the two uncovered branches are an older one in `HealthStatus.tsx` and an unreachable fallback in `screens.ts`); `make edge-check` exit 0. Every commit had a sabotage that turned its tests or `edge-check` red, restored with `cp`. In the browser at 390, 800, 1024, 1440 and 1904 px: chart labels 14 px, no horizontal overflow, the page ending at the footer, and the same Bahrain totals.

## Next

- Merge PR #26 once CI is green.
- The ADR 0016 content security policy blocks the Google Fonts stylesheet `index.html` links.
- Plan phase 6, the assistant.
