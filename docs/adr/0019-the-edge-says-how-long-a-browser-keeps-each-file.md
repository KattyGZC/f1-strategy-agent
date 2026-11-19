# 0019. The edge says how long a browser keeps each file

- Status: Accepted
- Date: 2026-11-18

## Context

nginx serves the frontend's build: `index.html`, and the scripts and styles under `/assets/`, whose names carry a hash of their content (Vite's build). It sends neither `Cache-Control` nor `Expires`, only `Last-Modified` and `ETag` (`curl -I http://localhost:8080/`, 2026-11-18). A browser may then reuse a stored `index.html` without asking the server for a time it guesses from `Last-Modified` (RFC 9111, 4.2.2, heuristic freshness). On 2026-11-18 a rebuilt stack kept serving the previous screen to a browser that had loaded it before, until the page was reloaded with the cache bypassed.

`location /` answers any path it has no file for with `index.html` (`try_files $uri /index.html`), so the screens' URLs load the app. A request for a hashed asset that no longer exists, such as one an old `index.html` names after a deploy, gets `index.html` with status 200.

The API sets no `Cache-Control` either, and its responses carry no `Last-Modified`, so a browser does not keep them.

## Options

1. **Leave caching to the browser.** Nothing to configure; an old `index.html` can outlive a deploy, and its scripts can be gone (ADR 0003 deploys on every merge).
2. **No caching at all (`no-store` everywhere).** Always current; every visit downloads the whole bundle again.
3. **By file:** `index.html` revalidated on every load (`no-cache`, answered 304 while it is unchanged), hashed assets kept for a year (`immutable`), and a missing asset answered 404.

## Decision

Option 3, at the edge in `frontend/nginx.conf`: one `Cache-Control` per kind of path, set at the server level, never in a `location`, so the security headers there are not dropped (ADR 0016). `/api/` keeps whatever the backend sends.

## Consequences

- A deploy reaches every browser on its next load: `index.html` is checked each time, and it names the new assets by their new hashes.
- `/assets/` answers 404 for a file it does not have, instead of `index.html`, so a stale name is never stored as a year-long copy of the page.
- The header is sent on success only (`add_header` without `always`), so an error is never kept.
- `make edge-check` asserts the three cases and the API's lack of the header.
