# 0024. The Sporting Regulations are kept per edition, split by article and embedded in pgvector

- Status: Accepted
- Date: 2026-11-23

## Context

The assistant answers rule questions applied to a race ("Why was there a safety car on lap 30?") by crossing race control with the FIA Formula 1 Sporting Regulations (`docs/specs/phase-6-assistant.md`). The spec left open which seasons are indexed, whether race control is embedded, and where the PDFs come from (open questions 1 to 3). Facts checked on 2026-11-23:

- **Editions.** The FIA publishes the regulations as PDFs on https://www.fia.com/regulation/category/110, several dated issues per season: 2024 from Issue 1 (2023-09-26) to Issue 7 (2024-07-31); 2025 from Issue 1 (2024-07-31) to Issue 5 (2025-04-30); 2026 as "FIA 2026 F1 Regulations - Section B [Sporting]", from Iss 01 (2024-10-17) to Iss 09 (2026-10-01).
- **File names do not follow one pattern:** `/sites/default/files/` or `/system/files/documents/`, `issue_7` or `iss_09` or `iss03`, some with suffixes.
- **Format.** The PDFs are text-based. Up to 2025, articles read `55) SAFETY CAR`, then `55.1 ...`, with points cited as `30.5n)`. In 2026 they read `B5.10 Formation Lap(s) Behind Safety Car`, then `B5.10.1`, with points `a.`, and the numbers sit in a margin column.
- **Copyright.** The FIA's website terms (https://www.fia.com/file/83930/download):
  - 3.4: the copyright of the sporting regulations "vests exclusively in the FIA".
  - 3.5: reproducing or distributing them without written consent "is strictly forbidden".
  - 3.6: "short extracts of FIA Publications may be quoted provided always that the corresponding FIA Publication is duly referenced".
  - 3.8: "Deep-linking to some pages of the Website is tolerated".
  - The terms do not say whether indexing the text privately for search is allowed. That is a legal question this ADR cannot settle.
- **Voyage AI.**
  - Embedding models (https://docs.voyageai.com/docs/embeddings): `voyage-4` is the current general-purpose and multilingual model, 32K tokens of context, 1024 dimensions by default (256, 512 or 2048 on request), and `input_type` `document` or `query`.
  - Price (https://docs.voyageai.com/docs/pricing): 0.06 USD per million tokens, after 200M free.
  - The FAQ (https://docs.voyageai.com/docs/faq) says "Voyage AI embeddings are normalized to length 1", and "Cosine similarity is equivalent to dot-product similarity".
  - The official SDK `voyageai` 0.6.0 depends on `requests`, `aiohttp`, `tenacity`, `numpy`, `aiolimiter`, `pillow`, `pydantic`, `tokenizers` and `langchain-text-splitters` (https://pypi.org/pypi/voyageai/json).
- **`pypdf`** 7.1.1 is BSD-3-Clause with no runtime dependency on Python 3.12 (https://pypi.org/pypi/pypdf/json). `pymupdf` is AGPL. The author approved `pypdf` on 2026-11-23.

## Options

1. **Commit the PDFs to the repository.** Reproducible offline, but the repository is public, so committing them would be the redistribution the terms forbid.
2. **Embed race control as well as the regulations.** But race control messages are rows with ids, which a query reaches exactly and cites by key; embedding them adds cost and a second, fuzzier path to the same fact.
3. **Download each edition from a manifest of URLs and hashes, store it as received, split it by article and embed only the regulations.**

## Decision

Option 3. Every edition in force at a race of the clean model is listed in a committed manifest, downloaded by `make ingest-rules`, kept as received in MongoDB, split by article, embedded with `voyage-4` at 1024 dimensions, and searched in the edition in force at the date of the race asked about. Race control is reached through the `race_control` tool, never embedded.

## Consequences

**The manifest.**
- `backend/src/f1_strategy/adapters/rules_manifest.json` (committed) lists per edition: the season, the document (`sporting`, or `sporting_section_b` from 2026), the issue, its revision (1 unless the FIA published more than one), its publication date, the PDF's URL on fia.com and its SHA-256.
- The URLs are written by hand from the FIA's listing, since the file names follow no pattern.
- Adding an edition is a manifest change.
- **The edition in force at a race** is chosen among the editions of the race's own season only: the one with the latest publication date on or before the race's `date_start`, ties broken by issue and then revision (2024's Issue 6 has a V1 and a V2). The season matters because the next season's first issue is published during this one: 2025's Issue 1 on 2024-07-31, 2026's Iss 01 on 2024-10-17. A race before its season's first issue has no edition, and `search_rules` answers so.
- 2026's Section A (General Provisions) is left out of V1.

**Ingestion.**
- `make ingest-rules YEAR=...` downloads each edition of the season that the raw store lacks, with the existing HTTP client, bounded and retried like the OpenF1 adapter.
- It checks the hash and stores the bytes as received in MongoDB, one document per edition, keyed by edition. A hash that differs fails the run and names the edition.
- Nothing is downloaded at request time.

**Splitting.**
- A pure domain function turns an edition's extracted text into articles, one chunk per numbered sub-article (`55.1`, `B5.10.1`), each with its number, its article's title, its page and its text. One parser handles each of the two numbering formats.
- An article longer than the embedding's useful size is split at its points (`a)`, `a.`), keeping its number.
- Text is extracted with `pypdf` in the CLI only.
- The tests use synthetic text in both formats, never the FIA's text, which is not ours to commit. Hypothesis properties check that splitting loses no text and keeps the numbers in order.

**Storage and search.**
- One migration adds `rule_edition` and `rule_chunk`:
  - `rule_chunk` is keyed by edition and article number, with title, page, text, a content hash and `embedding vector(1024)`.
  - It has an HNSW index with `vector_ip_ops`, since the vectors are normalized and inner product ranks them as cosine does.
  - Changing the model or the dimension is a new migration and a re-embedding (ADR 0002).
- `make embed YEAR=...` is a reconciling sweep, like transform and calibrate: a chunk is embedded again only when its content hash, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION` or `CHUNKER_VERSION` changes.
- Chunks are sent with `input_type` `document` and questions with `query`, within the documented batch limits.
- `search_rules` ranks the chunks of one edition by distance and keeps those whose score passes `RULES_MIN_SCORE`. That threshold is tuned on the golden questions. When none passes, the tool answers that no article matches, and the model says so (success criterion 6).

**Voyage over HTTP, not its SDK.**
- `adapters/embeddings.py` calls Voyage's embeddings endpoint with `httpx2`, validates the response with Pydantic, and owns its rate limit, retries (on 429 and 5xx only) and timeout, as the OpenF1 adapter does.
- This changes the spec's "through its official Python SDK": the SDK brings nine dependencies, two of them a second and a third HTTP client, for one call.
- The endpoint and its fields are checked against https://docs.voyageai.com/reference/embeddings-api when the adapter is written.

**Race facts are not embedded.** ADR 0002's context and `AGENTS.md` (Model and RAG) name curated race facts with their ids as material that may be embedded. V1 embeds none, since every race fact is a row a tool reaches by its key, and only the regulations need search by meaning. ADR 0002's decision, pgvector as the store, stands.

**What the visitor sees of the regulations.**
- An `article` citation shows the cited excerpt, capped at `RULES_EXCERPT_MAX_CHARS`, the edition it comes from, and a link to the FIA's own PDF at its page (`#page=N`).
- The API never serves a PDF or an article's full text. That is quoting short, referenced extracts and deep-linking, which the terms allow.
- Whether the private index itself needs the FIA's consent stays open. If the FIA objects, `make embed` and the manifest are the only places to change.
