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

M17 does not support semantic similarity, embeddings, external research, LLM reasoning, or
GraphRAG. A request for semantic or external routing fails explicitly.
