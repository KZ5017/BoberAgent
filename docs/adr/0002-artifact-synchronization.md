# ADR 0002: Chunked Artifact synchronization ownership

- Status: Accepted for Milestone 6
- Date: 2026-09-17

## Context

Node-created evidence must remain available through disconnection and synchronize without placing
bytes in Capability Results or sharing storage implementations across the Core/Node boundary.
Artifacts may arrive before Core has ingested their producing Run.

## Decision

Extend the neutral transport protocol with bounded start/chunk/finalize messages and explicit
acknowledgement or rejection responses. The Node owns spool bytes and persistent retry state. Core
owns resumable temporary files, SHA-256/size verification, content-addressed filesystem storage,
and catalog availability state. The transport owns only serialized messages.

Core preserves `created_by_run` as a logical `CapabilityRunRef` but no longer requires that Run's
database row before accepting evidence. This permits Artifact synchronization and Result delivery
to remain independently ordered without implementing Result ingestion.

## Consequences

Chunks carry explicit offsets and are independently bounded. Incomplete content is never exposed.
Core publishes verified bytes by atomic rename before committing `AVAILABLE` metadata; a crash may
leave an unreferenced content-addressed file but cannot expose partial bytes as complete. Identical
content may share a physical blob while every `ArtifactRef` and its provenance remain distinct.
