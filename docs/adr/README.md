# Architecture decision records

One decision per file, numbered in order. An accepted ADR binds the code (`AGENTS.md`). To change one, write a new ADR that supersedes it and mark the old one `Superseded by NNNN`; do not rewrite history.

| # | Decision | Status |
|---|---|---|
| [0001](0001-replay-instead-of-live-feed.md) | Replay historical sessions instead of consuming the live feed | Accepted |
| [0002](0002-pgvector-as-vector-store.md) | pgvector as the vector store | Accepted |
| [0003](0003-monorepo-with-continuous-deployment.md) | Monorepo with continuous deployment to production | Accepted |
| [0004](0004-mongodb-as-raw-document-store.md) | MongoDB as the raw document store | Accepted |
| [0005](0005-react-vite-typescript-frontend.md) | React, Vite and TypeScript for the frontend | Accepted |
| [0006](0006-raw-data-scope.md) | Raw data scope: Race and Qualifying by season, telemetry by session | Accepted; telemetry superseded by 0007 |
| [0007](0007-telemetry-of-the-latest-grand-prix.md) | Telemetry of the latest settled Grand Prix, one session kept | Accepted |
| [0008](0008-deterministic-clean-model.md) | A deterministic clean model: one transaction per session, replaced whole | Accepted |

## Template

```markdown
# NNNN. <Decision as a short sentence>

- Status: Proposed | Accepted | Superseded by NNNN
- Date: YYYY-MM-DD

## Context

What forces the decision. Facts carry their source.

## Options

1. **<Option>**: pros, cons.
2. **<Option>**: pros, cons.

## Decision

What we do, in one or two sentences.

## Consequences

What becomes easier, what becomes harder, what the code must now respect.
```
