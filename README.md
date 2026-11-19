# F1 Strategy Agent

[Español](README.es.md)

A Formula 1 platform being rebuilt in phases: a pipeline that ingests historical OpenF1 sessions and replays them as if live, a strategy simulator with a predictive tyre and lap-time model, and an assistant that answers with facts it retrieved and cites them. The plan, the standard the code follows and the current phase are in [AGENTS.md](AGENTS.md).

## What exists today

Phase 0, the foundation:

- **Backend** (`backend/`): Python 3.12, FastAPI, one endpoint, `GET /api/health`. Layered as domain, application and adapters; `import-linter` fails the build if an inner layer imports an outer one.
- **Frontend** (`frontend/`): React, Vite and TypeScript in strict mode. It shows the API status through a client generated from the backend's OpenAPI schema.
- **Infrastructure** (`infra/compose.yaml`): PostgreSQL with pgvector, MongoDB, Redis, the backend and the frontend.
- **CI** (`.github/workflows/ci.yml`): the same checks as `make check` on every pull request, a check that the generated client matches the API, mutation testing of the domain, and a smoke test of the full stack with the edge checks. `main` takes changes only through a pull request with these checks green; the owner can merge past a red one (ADR 0010).

Phase 1, ingestion:

- **Raw OpenF1 data in MongoDB**: every response of a season's Race and Qualifying sessions, one document per request, keyed by the endpoint and its parameters. A session is ingested once it ended at least `SESSION_SETTLE_H` hours ago (6 by default), so the season in progress works too: run it again after a race weekend and it adds only the new sessions. The client stays under OpenF1's free limit (3 requests per second, 30 per minute) and retries only errors that can succeed on retry.
- **Car telemetry** (`car_data`, `location`) of the latest settled Grand Prix, per driver in 30-minute windows. Only one session of telemetry is kept: when a new one is fully stored, the previous one is deleted, because each race weighs about 150 MB and the free MongoDB tier is 512 MB ([ADR 0007](docs/adr/0007-telemetry-of-the-latest-grand-prix.md)).

Phase 2, the clean model:

- **Typed tables in PostgreSQL** for every ingested session: meetings, sessions, drivers per session, laps, stints, pits, intervals, positions, race control, weather, results, qualifying phases, starting grid, overtakes and team radio. Times and gaps are exact numbers, a gap of "+1 LAP" is a lap count, closed sets are enums, and constraints reject what the 2024 season did not show ([ADR 0008](docs/adr/0008-deterministic-clean-model.md)).
- **A deterministic load**: the same raw data gives the same rows, whatever the order, the number of workers or a crash in the middle. Each session is replaced whole in one transaction, a rerun loads only what changed, and a session with bad data fails alone with the document and row that caused it.

Phase 3, the replay:

- **A replay API** over any session in the clean model: `POST /api/replays` starts one at 1x to 60x, `/pause`, `/resume` and `/speed` control it, `/seek` moves it to the earliest start of a lap ([ADR 0012](docs/adr/0012-seek-to-a-lap.md)), `DELETE /api/replays/{id}` stops it and frees its place ([ADR 0011](docs/adr/0011-a-viewer-stops-their-replay.md)), and `GET /api/replays/{id}/events` streams its laps, positions, intervals, pits, race control, weather, overtakes and team radio over Server-Sent Events, in the order and at the pace they happened. A viewer that reconnects resumes after its last event; after a seek the stream starts again with a reset, then what is still current at that lap (each driver's latest position, interval and lap, the latest weather, and every pit, race control message, overtake and team radio), so a late lap shows in under a second ([ADR 0013](docs/adr/0013-a-seek-sends-what-is-still-current.md)). The events go through a Redis stream per replay; the same session always gives the same stream ([ADR 0009](docs/adr/0009-replay-from-the-clean-model.md)).
- **The loaded sessions**: `GET /api/sessions` lists every session in the clean model with its meeting, the latest first, and `GET /api/sessions/{session_key}` adds its drivers with their team and colour, and its last lap number.
- **The replay screen** at http://localhost:8080: pick a Grand Prix, one of its sessions and a speed, and watch it as it happened: the leader's lap and the latest flag for the whole track, the timing tower (position, interval or gap to the leader, last lap, tyre and its age, last stop), the last lap of the driver you follow with its sectors and speed traps, the weather and race control. Pause, resume and change the speed while it plays, or type a lap and go to it: the screen rebuilds as it was at that lap's start and plays on; choosing another session stops the replay you leave. The circuit map and the strategy tools have their place on the screen but are not built yet. Every number on the screen came in an event: the screen keeps the latest value of each, and every race control message.

Phase 4, the predictive engine:

- **A lap-time model per race**, calibrated on its clean laps: for each compound a base lap time and a degradation per lap of tyre age, one slope per lap of race shared by the dry compounds (fuel burn and track evolution together, since there is no fuel data) and one for intermediates (the track dries while they run), and each driver's pace against the average car. A lap counts only when nothing else explains its time: lap 1, pit laps, safety car, virtual safety car and red flag periods and the lap after them, slick laps in the rain and the 20 minutes after it, and outliers are left out, each with its reason ([ADR 0014](docs/adr/0014-per-race-linear-lap-time-model.md)).
- **Predictions of a stint**: given a compound, the tyre's age, the first lap and the number of laps, the lap time of each lap, for a driver or the average car, flagged when the tyre is older or newer than any lap the race calibrated. Holding out each driver's last stint of at least 10 clean laps and predicting it from the rest of the race, the mean error per lap is 0.46 s in the median and 0.80 s at the 90th percentile on dry tyres over the 2024 season.
- Not calibrated yet, and said so: starting fuel, wind, driver aggressiveness, full wet tyres and Sprints. Track temperature is recorded per race, not fitted.

Phase 5, the simulator:

- **The pit loss of each race**, measured on its own stops: a stop costs its in-lap and out-lap over the driver's lap before and lap after, and the race's value is the median of its usable stops (19.2 s at Spa to 29.5 s in Singapore in 2024). Rain does not exclude a stop, since the laps around it run in the same rain; stops under a safety car, virtual safety car or red flag, next to another stop or right after lap 1 do, each with its reason. A race measured on fewer than 5 stops keeps its value, marked as not reliable: Interlagos in 2024, with 1 ([ADR 0015](docs/adr/0015-pit-loss-from-neighbouring-laps.md)).
- **Every request is traceable by one id**: each API response carries `X-Request-ID`, and the backend logs one JSON line per request (method, route template, status, error code, duration) and every other line under that id. Every error answers `{"detail", "code", "request_id"}`, with `code` from a closed list, and the screen shows the request id next to the error. An unexpected failure is logged once with its traceback and answers 500 without it. `GET /api/health/ready` checks PostgreSQL and Redis and answers 503 naming the one that does not answer; the stack's healthcheck uses it. At the edge, nginx gives every request its own id (never the client's), answers a body over 8 KB with 413 `payload_too_large` and more than 30 requests per second from one address (bursts of 60) with 429 `rate_limited` in the same shape, and sets a content security policy and the other security headers on every response ([ADR 0016](docs/adr/0016-request-tracing-and-edge-limits.md)). It also tells the browser to check `index.html` on every load and to keep the hashed scripts and styles for a year, and answers 404 for one the build no longer has, so a new build reaches every browser on its next load ([ADR 0019](docs/adr/0019-the-edge-says-how-long-a-browser-keeps-each-file.md)).
- **Strategies simulated on a race's calibration**: several strategies of stints (compound, laps, tyre age at the start), for a driver or the average car. Each lap is the model's prediction, each stop adds the race's pit loss once, and each strategy gets its total race time and its gap to the fastest; one the race cannot run (laps that do not add up to the race, a compound it did not calibrate, a stop where there is no pit loss) is rejected with its reason and the stint. Each result names its caveats (a pit loss not reliable, a tyre age outside the calibrated ones, one dry compound only) and what the model leaves out: the standing start, starting fuel, wind, driver aggressiveness, track temperature, and rain on slick tyres in the 4 races of 2024 that had rain, now counted with each calibration ([ADR 0017](docs/adr/0017-strategy-simulation-in-the-race-it-was-calibrated-on.md)).
- **A simulator API**, after `make calibrate`: `GET /api/races` lists the calibrated races, the earliest first, and `GET /api/races/{session_key}` gives what one race's model carries, so a form can be built from it: its laps, the compounds a stint can run with their calibrated tyre ages and error, the drivers with a calibrated pace, the pit loss and whether it is reliable, the track temperature, the rain readings and what is not modelled. `POST /api/simulations` takes the race, an optional driver (none is the average car) and 1 to 4 strategies of 1 to 6 stints, and answers each strategy simulated or rejected, in order; nothing is stored. A race or driver without a calibration answers 404 `race_not_calibrated` or `driver_not_calibrated`, a body outside those bounds 422. At the edge, `/api/simulations` is also limited to 5 requests per second per address (bursts of 10).

- **The simulator screen**, the Simulator tab next to Replay: pick a calibrated race and a driver or the average car, and build up to 4 strategies of up to 6 stints from the compounds that race calibrated, each stint with its laps and the tyre's age at its start. The screen shows the race's model (laps, pit loss and whether it is reliable, track temperature, model error, the calibrated compounds and their tyre ages), then each strategy as the API answered it: its total, its gap to the fastest, its stops and caveats, or why it was rejected; a chart of every simulated strategy's lap times, dashed where the tyre is older or newer than any the race calibrated, with each stop marked; and what the simulation leaves out. The open tab lives in the URL (`#/replay`, `#/simulator`), so a reload or a link opens it again, and a replay keeps playing behind the simulator ([ADR 0018](docs/adr/0018-screens-state-and-charts-in-the-frontend.md)).

The assistant does not exist yet.

## Run it locally

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node.js 22 and GNU Make.

```sh
cp .env.example .env
make up
```

Open http://localhost:8080; the replay screen lists the sessions loaded with `make transform` (below), and the Simulator tab the races calibrated with `make calibrate`. `make down` stops the stack. `make up` also brings the PostgreSQL schema to the latest migration; `make migrate` does only that. A `.env` copied before phase 2 needs the new `POSTGRES_CONNECT_TIMEOUT_S` and `TRANSFORM_*` lines from `.env.example`, and one copied before phase 3 the `POSTGRES_POOL_SIZE`, `REDIS_*` and `REPLAY_*` lines, `REPLAY_APPEND_BATCH` included; one copied before phase 5 needs `LOG_LEVEL` and `READINESS_TIMEOUT_S`.

Ingest raw data while the stack is up:

```sh
make ingest YEAR=2026              # settled Race and Qualifying sessions, about 20 minutes per full season
make ingest-telemetry              # car_data and location of the latest settled Grand Prix
make ingest-telemetry SESSION=9472 # or of another session (2024 Bahrain race); either replaces the stored telemetry
```

If a run fails, it exits with code 1 and one line naming the request that failed. Run the same command again: what was stored is skipped and the run continues from there.

Load an ingested season into the clean PostgreSQL model:

```sh
make transform YEAR=2026 # every ingested session that changed since its last load, in about a minute per season
```

A session whose raw data is still incomplete waits for the next run; a session whose data the schema does not describe fails alone, with one line naming the document and the row, and the run exits with code 1. Running it again loads only what changed (ADR 0008).

Calibrate the lap-time model of every race of a transformed season:

```sh
make calibrate YEAR=2024 # each race whose clean rows or model changed, in a few seconds per season
```

A race whose clean laps cannot determine the model is recorded as not calibrated, with its reason; one whose race control the model does not describe fails alone, naming the message, and the run exits with code 1. A transform that reloads a race drops its calibration, and the next run computes it again (ADR 0014). The calibration holds the race's pit loss too; a calibration made before it existed is computed again on the next run (ADR 0015). `make migrate` removes the calibrations made before rain readings were counted, and the next run computes them again (ADR 0017).

## Develop

```sh
make install    # backend and frontend dependencies
make check      # lint, format, types, layer rules, tests with coverage, build, API contract
make fast-check # the static half of make check, in about a minute; Claude Code runs it before a commit
make mutation   # mutation testing of the domain in a Linux container; fails if a mutant survives
make edge-check # against a running stack: request ids, error shape, limits and headers at nginx
make format     # apply the formatters
make openapi    # regenerate the frontend API client after changing an endpoint
```

## How it is built

Decisions are recorded in [docs/adr/](docs/adr/README.md). Each working session with the AI coding agent leaves an entry in [docs/devlog/](docs/devlog/README.md).
