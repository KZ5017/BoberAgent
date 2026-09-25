# Curated Knowledge sources

M17 canonical Knowledge is maintained here as UTF-8 Markdown with TOML front matter delimited by
`+++`. `reference/` contains explanatory documents; `procedures/` contains structured operational
guidance. Only these two explicitly configured directories are loaded. Paths and filenames are
source locations, never Knowledge identities.

Reference front matter uses `id = "knowledge..."`, positive integer `version`, `title`, `type`,
`status`, and `source_kind`. Procedure front matter uses `id = "procedure..."`, positive integer
`version`, `title`, `status`, `source_kind`, `goal_type`, nonempty `completion_conditions`, and at
least one `[[steps]]` table with `step_id`, `capability_id`, `operation`, and `purpose`. Optional
structured fields are described by the models in `boberagent_core.knowledge`. Status is one of
`DRAFT`, `CANONICAL`, `DEPRECATED`, or `ARCHIVED`; one ID may have only one current canonical
version. Historical versions remain available by explicit ID and version.

`source_kind` records curation provenance, while the loader adds a root-relative source path and
SHA-256 of the exact file bytes. The original Markdown body and heading paths are retained without
creating semantic chunks. A changed byte changes the hash; relocation alone does not change the
logical ID or content hash. Broken cross-references and duplicate canonical declarations fail
loading. Procedure capability IDs can be checked against a caller-supplied known-ID set; no tool
implementation is imported into Core.

Consumers use `KnowledgeRouter.from_directory(Path("knowledge"))` and its exact or structured
`resolve()` API. Reload creates a new validated snapshot; a failed reload leaves the old snapshot
untouched. Procedure steps are guidance, not active Workflow steps: the M11 Workflow layer still
supplies Mission-specific inputs, scope projections, lifecycle, and capability dispatch. There is
no automatic Mission/Artifact/Observation promotion into this global directory. Curators must
review source content, including potential sensitive material, before adding it here.

M18 adds optional **derived semantic discovery** without changing those deterministic M17 routes.
Construct a `SemanticRetrievalService(root=selected_root, provider=provider, index=index)` and pass it
to `KnowledgeRouter.from_directory(selected_root, semantic_service=service)`. Call
`router.refresh_semantic()` explicitly after loading or changing curated sources; then use
`KnowledgeRequest(semantic_query="...", domain="...", semantic_limit=10)`. Exact IDs still win,
and metadata-only requests still use deterministic filtering. Semantic requests without an index
raise `SemanticUnavailable`; stale/incompatible generations raise typed errors. External research
remains unavailable.

`EmbeddingProvider` accepts ordered text batches and returns ordered vectors with provider/model
identity and dimension. `OpenAICompatibleEmbeddingProvider` uses only `POST /v1/embeddings`; configure
`EmbeddingHTTPConfiguration` with an explicit base URL, model ID, optional bearer key, timeout, and
bounded batch size. The URL may end before or at `/v1`. It does not call native LM Studio APIs or
`/v1/models`. The provider validates indexes, count, finite values, dimensions, and returned model.
Normal tests use deterministic fake vectors and need no embedding service.

`SemanticIndex` is the provider-neutral index boundary. The initial
`boberagent_core.knowledge.qdrant_local.QdrantSemanticIndex(explicit_index_directory)` stores an
on-disk Qdrant-local projection, separately from the curated Markdown root. Qdrant local permits
one client per index path; close it before reopening. It is not a server, distributed index, or
canonical Knowledge store. Its active manifest records provider/model/dimension, source root and
revisions, and versioned chunk formats. A full refresh builds a new generation and then switches
the active pointer; changed, moved, deleted, or no-longer-canonical sources require refresh.
A stale/incompatible index is never silently queried. Prior generations may remain on disk.

`SemanticChunk` preserves exact body-slice text and offsets separately from deterministic embedding
input (`Title: ... / Section: ... / body`). `section-blocks-v1` groups heading-governed body by
paragraph, list, table, and fenced-code blocks and only hard-splits oversized blocks; headings are context, never
standalone semantic hits. `title-heading-body-v1` is the embedding-input format. UUIDv5 chunk IDs
derive from logical source ID, version, chunking version, heading path, repeated-heading occurrence,
and within-section ordinal—not file path or offset. Source/chunk hashes, provenance, and section
and document ordinals remain separate for audit and future source-order reconstruction. Search
uses Qdrant payload filters and Cosine scores; ties use source ID, version, document ordinal, then
chunk ID. Scores are relevance only, not operational authority.

The configured Knowledge root may be the `BOBER_AGENT` subdirectory of an Obsidian vault, but the
loader never scans its parent. M18 does not index Mission data, raw Artifacts, Secrets, or arbitrary
external pages. Curation must still avoid sensitive authored prose. No GraphRAG, LLM Reasoner,
Context Builder, prompt construction, or M19 behavior exists here; see
[ADR 0011](../docs/adr/0011-derived-semantic-retrieval.md).
