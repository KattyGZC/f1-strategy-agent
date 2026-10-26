# 0005. React, Vite and TypeScript for the frontend

- Status: Accepted
- Date: 2026-10-26

## Context

The frontend has two screens, the strategy simulator and the assistant chat, and a live view of a replayed session (ADR 0001). It renders what the API returns and computes nothing (`AGENTS.md`, Architecture). Request and response shapes come from the OpenAPI schema FastAPI emits, through a generated client (`AGENTS.md`, Owners). It deploys on every merge (ADR 0003), so the build must be simple.

Vite facts (vite.dev/guide/, read 2026-10-26): it offers a `react-ts` template; its build "bundles your code with Rolldown, pre-configured to output highly optimized static assets for production"; it "requires Node.js version 20.19+, 22.12+".

## Options

1. **React + Vite + TypeScript, as a single-page app.** The build is static files, served by any static host or by a plain web server container. No server runtime to operate.
2. **Next.js.** Server rendering and routing out of the box, at the cost of a Node server in production and a second place where data could be fetched or computed. The project needs neither SEO nor server rendering.
3. **Server-rendered templates from FastAPI.** No second toolchain, but interactive charts and streaming chat become hand-written JavaScript without types.

## Decision

Option 1. The frontend is a React single-page app built with Vite, in TypeScript with `strict` on, talking to the API only through a client generated from the OpenAPI schema.

## Consequences

- The frontend image or bundle is static; there is no Node process in production.
- The generated client is regenerated in the same change that alters an API shape, and CI fails if it is out of date.
- Node.js 22 (or 20.19+) is required locally and in CI.
- Routing, state and chart libraries are chosen in phase 5, when the simulator UI is built.
