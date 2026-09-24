# ADR 0010: File-backed deterministic Knowledge foundation

- Status: Accepted for Milestone 17
- Date: 2026-09-24

## Context

The normative Knowledge model separates reusable curated material from Mission World State and
prioritizes deterministic Procedure lookup. M17 needs stable identities, versioning, validation,
and provenance before semantic retrieval exists. The existing Core Workflow Engine already owns
durable execution state and must not be duplicated by Procedures.

## Decision

Core loads explicitly maintained Markdown under `knowledge/reference/` and
`knowledge/procedures/`. TOML front matter is used because Python 3.12 parses it without an extra
dependency. Logical IDs and positive integer versions identify items; paths are provenance only.
The SHA-256 of exact source bytes identifies a loaded revision. One current `CANONICAL` version per
ID is permitted, while other versions remain explicitly retrievable. Loading and cross-reference
validation build a fresh immutable repository/registry snapshot; reload never mutates a valid old
snapshot on failure.

Procedure steps name candidate Capability IDs and operations, but hold no Mission inputs or
execution state. A Workflow must explicitly instantiate any executable definition and retains all
M11 dispatch, scope, lifecycle, and Result semantics. The Knowledge Router handles exact IDs and
structured metadata only; semantic and external requests fail clearly.

## Consequences

No Core database migration is needed. Source review and repository access control are the
curation gate; the loader rejects Mission/Secret reference metadata but does not claim to detect
arbitrary sensitive prose. Mission Artifacts and Observations have no automatic ingestion path.
M18 semantic indexes will be derived from these canonical sources, not authoritative storage;
M19 reasoning remains separate. No vector database, LLM, Obsidian, or GraphRAG dependency exists.
