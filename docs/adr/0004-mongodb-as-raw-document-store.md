# 0004. MongoDB as the raw document store

- Status: Accepted
- Date: 2026-10-26

## Context

The pipeline stores every OpenF1 response as received, once per request, before any cleaning (`AGENTS.md`, Data and Owners). The store must enforce that a request is written once, keyed by `endpoint` + query params + `session_key`, so re-running ingestion is idempotent without a lookup in application code. It must be queryable, so the async transform can select the raw documents of one session, and it must have an async Python driver, because I/O is async end to end.

The first MVP copied raw JSON to S3 through LocalStack. An object store has no unique index and no query by field, so idempotency and selection lived in code.

MongoDB facts (read 2026-10-26):

- The official Python driver ships an async API: "The PyMongo Async API is designed as a unification of PyMongo and the Motor library", and "Motor will be deprecated on May 14th, 2026" (mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/).
- The Atlas free cluster (M0) offers "512 MB of storage" and "Up to 100 operations per second" at $0 (mongodb.com/pricing).

## Options

1. **MongoDB.** A document store with unique indexes and queries by field. Official async driver (`AsyncMongoClient`). One container locally, a free managed tier for production.
2. **S3 or MinIO.** Cheap and simple, but no unique constraint and no query by field; idempotency and selection would be reimplemented in code.
3. **DynamoDB Local.** Conditional writes give idempotency, but queries are limited to the key design, and it ties the project to AWS.

## Decision

Option 1. Raw responses are written to MongoDB through one adapter that uses PyMongo's async API, with a unique index on the idempotency key declared by the adapter's setup, not by hand.

## Consequences

- `motor` is not used; the adapter imports `pymongo` only.
- A duplicate request is rejected by the unique index, and the adapter treats that as "already stored", not as an error.
- Raw documents are never updated after they are written. A correction is a new ingestion run, not an edit.
- The free tier's 512 MB is a ceiling for production raw data. Phase 1 measures the size of one season before deciding what is kept in production; until it is measured, fitting a season is not assumed.
- LocalStack and `boto3` leave the stack when the MVP is replaced.
