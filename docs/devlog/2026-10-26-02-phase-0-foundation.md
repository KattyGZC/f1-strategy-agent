# 2026-10-26 · 02. Phase 0: foundation

**Goal:** settle the document store and the frontend stack, then build the monorepo foundation: tooling, one `make check`, CI and containers.

## What happened

1. The session opened from the previous entry's Next: phase 0, starting with two decisions.
2. The agent recommended MongoDB for raw documents and React with Vite and TypeScript for the frontend; the author accepted both. Recorded as [ADR 0004](../adr/0004-mongodb-as-raw-document-store.md) and [ADR 0005](../adr/0005-react-vite-typescript-frontend.md), with facts read from the vendors' docs during the session.
3. The agent checked the local toolchain (no `make`, no `uv`, Python 3.11 against a 3.12 requirement) and asked three questions before planning. The author chose uv over Poetry, installing GNU Make over switching to `just`, and deleting the first MVP in this phase instead of excluding it until phase 2.
4. The agent posted the owner check and the plan, and built it after the author's OK: `backend/` (FastAPI, `GET /api/health`), `frontend/` (a page that shows the API status through a client generated from the OpenAPI schema), `infra/compose.yaml` (PostgreSQL with pgvector, MongoDB, backend, frontend), the root `Makefile`, the CI workflow, and the rewritten README with a Spanish twin.

## Decisions

- **MongoDB as the raw store**: a unique index enforces one write per request; official async driver. [ADR 0004](../adr/0004-mongodb-as-raw-document-store.md).
- **React, Vite and TypeScript**: a static build, no Node server in production. [ADR 0005](../adr/0005-react-vite-typescript-frontend.md).
- **uv, GNU Make, MVP deleted**: author's choices on the three questions above.
- **Layer rule enforced by a tool**: `import-linter` fails the build if an inner layer imports an outer one.
- **The API contract is checked**: `make check` and CI fail when the generated client differs from the backend's OpenAPI.

## Corrections and redirections

The author did not redirect the agent this session. The agent changed course on its own in these places:

- The settings module in the plan was not built, because phase 0 reads no variable; it arrives with the first one.
- The Vite template now ships oxlint, so it replaced the planned ESLint.
- TypeScript was pinned to 5.9 because `openapi-typescript` does not support 6, rather than forcing the install.
- Tests exposed that the frontend client built relative URLs that fail outside the browser; `baseUrl` became required.
- Grading found a request not cancelled on unmount, a lint rule (`PLR2004`) disabled globally, and a frontend container without a healthcheck. All three were fixed before presenting.
- Agent mistakes, caught and fixed in the session: a uv Docker image tag that does not exist; a healthcheck on `localhost` that resolved to IPv6 while nginx listened on IPv4; a first commit that also contained the MVP removal, redone on the unpushed branch before review; `astral-sh/setup-uv@v10` in CI, a tag the project does not publish (it only tags full versions), which failed the first run of the backend and contract jobs and was pinned to `v10.3.2`.

## Verification

- `make check`: exit 0. Backend 4 tests at 100% branch coverage; frontend 6 tests at 100%; import-linter "1 kept"; contract check with no diff.
- Sabotage: dropping the `/api` prefix turned 3 tests red; changing the status text, 2; removing the request cancellation, 1. All restored.
- Contract: bumping the API version made `make openapi-check` exit 2; restored, exit 0.
- Reset: `docker compose down -v`, then `make up`: four services healthy, `GET /api/health` through nginx returned `{"status":"ok"}`, and the page rendered "API status: ok" in a browser.
- actionlint on the workflow: no findings. actionlint does not resolve action tags, so it did not catch the missing `setup-uv@v10`.
- CI on [PR #2](https://github.com/KattyGZC/f1-strategy-agent/pull/2): the first run failed in backend and contract (`Unable to resolve action astral-sh/setup-uv@v10`); after the pin, all five jobs passed (changes, backend, frontend, contract, stack).

## Next

- Phase 1, ingestion: the async OpenF1 client within the free rate limit, raw documents in MongoDB, and the settings module with the first variables. Measure the size of one season against the 512 MB free tier (ADR 0004).
