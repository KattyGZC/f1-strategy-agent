# 0002. pgvector as the vector store

- Status: Accepted
- Date: 2026-10-26

## Context

The assistant retrieves context (regulations, curated race facts) by semantic similarity before the model answers. The clean, structured data already lives in PostgreSQL, and the first MVP already ran the `pgvector/pgvector:pg16` image with a `Vector(768)` column.

## Options

1. **pgvector inside the PostgreSQL we already run.** One engine less to deploy, back up and secure. Vectors sit next to the rows they describe, so a query can filter by `session_key`, season or document type and rank by distance in one statement. HNSW indexes are supported.
2. **A dedicated vector database (Qdrant, Weaviate).** Better at very large collections and richer filtering, at the cost of another service in every environment and a second source of truth to keep in sync.

## Decision

Option 1. Embeddings are stored in PostgreSQL with pgvector.

## Consequences

- The vector column, its dimension and its HNSW index with the distance operator are declared in a migration.
- Each embedded chunk carries the ids of its source (document and section, or `session_key` and the fact's key), so answers can cite it.
- Changing the embedding model changes the dimension: that is a new migration plus a re-embedding job, never an in-place edit.
- If the collection outgrows PostgreSQL, a dedicated store goes behind the same retrieval port in a new ADR.
