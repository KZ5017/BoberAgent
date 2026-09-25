# ADR 0011: Derived semantic retrieval for curated Knowledge

Status: Accepted for Milestone 18.

## Decision

The M17 Markdown Repository and Procedure Registry remain canonical. `KnowledgeRouter` keeps exact
Procedure ID, exact Knowledge ID, and metadata-only routes deterministic. A `semantic_query` uses
an optional Core-owned `SemanticRetrievalService`; absent, stale, or incompatible semantic state
fails with a typed error and does not disable deterministic routes.

The service accepts an `EmbeddingProvider` and `SemanticIndex` protocol. Its first provider adapter
uses only OpenAI-compatible `POST /v1/embeddings` (including LM Studio deployments that expose
that endpoint). It does not use native LM Studio APIs, model-management probes, or chat APIs. The
first index adapter uses Qdrant local/on-disk with Cosine vectors. No Qdrant API escapes that
adapter. Qdrant local is single-client per index path and is not a distributed service. The
embedding model ID and source/index directories must be selected explicitly by the caller.

Only validated, curated canonical `reference/` and `procedures/` Markdown beneath the configured
Knowledge root enters the index. An Obsidian `BOBER_AGENT` directory may be selected as that root;
the rest of its parent vault is outside scope. Mission Observations, Artifacts, credentials,
Secrets, scanner output, and arbitrary external research are not indexed automatically. Human
curation is still responsible for avoiding secrets in authored prose.

## Chunks and generations

`section-blocks-v1` groups governed body text by heading section and paragraph/list/table/fenced-code runs;
oversized single blocks use a newline-aware hard split, then a fixed bound as final fallback.
Headings alone do not form semantic hits. `title-heading-body-v1` builds a separate deterministic
embedding input with document title, full heading path, and source text. The exact display text
remains a body slice with character offsets. Every child chunk retains its heading context.

Chunk ID is UUIDv5 of `source logical ID : version : chunking version : heading path :
same-path occurrence : within-section ordinal`. The filesystem path and offsets are not identity.
The chunk separately records source SHA-256, chunk SHA-256, provenance, section/document ordinals,
and body-relative offsets. Repeated headings remain distinct. Moving a file can therefore keep
logical chunk IDs while refreshing stored provenance.

An active manifest records format, provider/model, vector dimension, chunking and embedding-input
versions, source-root digest, source revisions/paths, count, and creation time. Refresh builds an
entire new local Qdrant generation before atomically changing the active manifest pointer. A
failed embedding/build keeps the previous generation but changed canonical sources cause stale
searches to fail until refresh. Deleted or no-longer-canonical sources disappear on rebuild. Old
generations may remain on disk and can be removed by an operator after the active generation is
confirmed; no concurrent index writers or automatic retention policy are promised.

Metadata filters run as Qdrant payload filters, not post-ranking suggestions. Scores are Cosine
similarities, not calibrated probabilities or security judgments. Equal scores are ordered by
source identity, version, document ordinal, and chunk ID. This is discovery only: Procedure
selection/execution remains deterministic and Core-owned. M19 reasoning, context assembly,
GraphRAG, chat/completion, and Obsidian MCP are deferred.
