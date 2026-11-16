# 0016. Every request is traceable by one id, and the edge bounds what reaches the API

- Status: Accepted
- Date: 2026-11-15

## Context

Phase 5 adds the first API endpoint that computes on arbitrary input (the strategy simulator), and the author asked that a failure be easy to trace to its origin. `AGENTS.md` leaves observability and production hardening to phase 7, but this phase needs a minimum of both before that endpoint exists. Facts read in the code on 2026-11-15:

- The backend writes no log of its own. uvicorn prints a plain-text access line per request (`backend/Dockerfile` runs it with its defaults), with the raw path and no id.
- An error answers `{"detail": "<message>"}` (`adapters/http/app.py`, `_status_handler`); a validation error answers FastAPI's `{"detail": [<errors>]}`; an unhandled exception answers uvicorn's plain-text 500. Nothing in a response ties it to a log line.
- `GET /api/health` answers `ok` without looking at PostgreSQL or Redis, and the compose healthcheck uses it (`infra/compose.yaml`).
- `frontend/nginx.conf` proxies `/api/` with no body limit beyond nginx's 1 MB default, no rate limit, no security header, nginx's default HTML error pages and no SSE tuning. The replay stream works through it because events arrive more often than the 60 s default read timeout.
- The frontend loads no external script, style or image; its only inline styles are React `style` props (`DriverCard.tsx`, `TimingTower.tsx`), which a `style-src 'self'` policy allows since they are set through the DOM.
- There is no CORS middleware; the browser reaches the API on the same origin, through nginx in the stack and the Vite proxy in development.

## Options

1. **Defer to phase 7.** Nothing to build now; the simulator would ship with untraceable failures and no bound on load.
2. **A request id, JSON logs, one error shape, a readiness check and limits at the edge, with the standard library.** Traceable today, no new dependency; no metrics or traces.
3. **OpenTelemetry and Prometheus now.** Traces and metrics, but nowhere to look at them before phase 7, and two SDKs to own.

## Decision

Option 2. Every request carries one id, through nginx, every backend log line, the response header and every error body; errors have one shape with a closed `code`; `/api/health/ready` checks the stores; nginx bounds bodies and request rates and sets security headers. Metrics, traces, TLS and auth stay in phase 7.

## Consequences

- **Request id.** nginx always sets `X-Request-ID` to its own `$request_id` (32 hex characters) and never forwards the client's. The backend takes the header when it matches `^[A-Za-z0-9-]{1,64}$` and generates one otherwise (development, through Vite), so a client cannot inject text into the logs. It is returned as `X-Request-ID` on every response.
- **Error shape.** Every error from the API is `{"detail": str, "code": ErrorCode, "request_id": str}`, documented in OpenAPI. `ErrorCode` is a closed enum, one value per cause: `replay_not_found`, `session_not_loaded`, `lap_not_found`, `replay_failed`, `too_many_replays`, `invalid_request` (422, with the validation errors under `errors`), `route_not_found`, `method_not_allowed`, `not_ready`, `internal_error`; nginx answers `payload_too_large` (413) and `rate_limited` (429) in the same shape. A client and a log search branch on `code`, never on the text of `detail`.
- **Logs.** One JSON object per line on stdout, from the standard library `logging` configured once in `adapters/observability.py`: `ts` (UTC), `level`, `logger`, `event`, `request_id`, and the event's own fields. uvicorn's access log is off and its own loggers write through the same formatter. Each request logs one `request` line when its response ends: method, route template (`/api/replays/{replay_id}`, never the raw path), status, `code` when it failed, and `duration_ms`; a stream logs when it closes. `LOG_LEVEL` is a required setting.
- **Unexpected exceptions.** The request middleware logs one `unhandled_error` line with the traceback, the route and the request id, and answers 500 `internal_error`; the traceback never reaches the response. When the response had already started (a stream), it logs and re-raises so the server closes the connection.
- **Readiness.** `GET /api/health/ready` runs `SELECT 1` on PostgreSQL and `PING` on Redis, both at once, each bounded by `READINESS_TIMEOUT_S`, and answers 200 with each dependency `ok`, or 503 `not_ready` naming the failed one; each failure is logged with its exception type. `GET /api/health` stays the liveness check; the compose healthcheck moves to `ready`.
- **Edge limits.** `client_max_body_size 8k` on `/api/` (the largest body planned, a simulation of 4 strategies of 6 stints, is under 3 KB); `limit_req` per client address at 30 requests per second with a burst of 60 on `/api/`; the simulator's endpoint gets its own, tighter zone when it lands. `server_tokens off`. Behind another proxy (phase 7) the client address needs `real_ip`; until then nginx is the edge.
- **Security headers** on every response: `Content-Security-Policy: default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy: same-origin` and a `Permissions-Policy` that denies camera, microphone and geolocation. HSTS waits for TLS.
- **SSE.** The replay events route is proxied with buffering off and a one-hour read timeout, so a quiet stream is not cut at 60 s.
- **No CORS**, on purpose: the API has one origin. Adding one is a new decision.
- **The frontend** shows the request id with every API error it displays, so a failure seen on screen can be found in the logs.
- **Limits named in config:** the backend values are settings (`LOG_LEVEL`, `READINESS_TIMEOUT_S`, both in `.env.example`); the edge values live in `frontend/nginx.conf`, the edge's own config.
