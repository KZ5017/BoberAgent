# M20-B — Immutable acquisition and provenance

## Goal and dependency

Turn **one selected M20-A candidate** into a reproducible source Artifact. Acquisition is not
installation, import, build, or execution. It must preserve source identity and prove that later
inspection and execution refer to the same bytes. Candidate selection requires an explicit
Mission/hypothesis relationship and source URI; a search hit alone is not executable intent.

## Typed boundary

| Input | Output |
| --- | --- |
| Selected `PoCCandidate`, `MissionRef`, source URI/repository identity, proposed immutable revision, acquisition limits | Acquisition record, pinned revision, source `ArtifactRef` with SHA-256/size and file inventory, source metadata and retrieval timestamp, optional managed `WorkspaceRef` |

For a mutable repository, resolve a commit/revision **before** retrieving content; record both
the originally advertised URI/ref and resolved immutable revision. Prefer a reproducible archive
or an explicitly inventoried file set. Hash acquired bytes and, for multi-file source, capture a
deterministic manifest of relative paths, file hashes, sizes, and modes. The source Artifact is
immutable evidence. A Workspace is a managed runtime-local staging area, not a canonical source
ID. The existing Node Artifact spool and neutral chunked sync publish verified bytes to Core;
`ArtifactRef` is stable end-to-end. If bytes are still Node-local, Core must report content not
yet available rather than pretending they can be inspected centrally.

Capture provenance: provider/source URI, repository identity, commit/revision, retrieval time,
content hashes, retrieved-file inventory, acquisition tool/version when known, redirect/final URI
and whether source material was modified by retrieval. Original names are metadata only; reject
path traversal, absolute paths, symlink escapes, archive bombs, oversized files, and unexpected
file types/volumes under explicit limits. Do not trust repository scripts or submodule hooks.

The execution path must consume the pinned Artifact (or a verified materialization of it), never
re-clone a branch or silently refresh dependencies. Recheck content hash after staging and before
execution. If a later revision is desired, create a new acquisition record/Artifact and redo
inspection and validation. This closes the source TOCTOU boundary; mutable external URLs remain
provenance, not execution references.

## Reuse, additions, and non-goals

Reuse SDK Workspace/Artifact APIs, Node local spool, M6 sync, Core Artifact catalog/storage,
and existing hash/size verification. A narrow acquisition capability/provider adapter and
Core-owned acquisition record are likely new. Keep source-network access and repository commands
managed by the Execution Node; do not add direct Core filesystem or capability implementation
imports. The exact source-fetch protocol belongs behind an adapter. Do not create a global
package cache or treat a checkout path as Artifact identity.

No `setup.py`, install script, build hook, package import, README command, PoC run, or automatic
Knowledge promotion occurs in this phase. No secret material enters the acquisition query or
record.

## Stop, security, and tests

Stop on unpinnable revision, hash/inventory inconsistency, source redirect outside allowed
destinations, size/path violations, unavailable Artifact content, or ambiguous repository
identity. Preserve a diagnostic and any safe partial evidence, but mark acquisition incomplete;
M20-C cannot inspect it as finalized source.

Tests: mutable branch pinned to a commit, changed upstream content producing a new Artifact,
identical retry idempotency, truncated transfer, Core/Node restart, hash mismatch, malicious
archive paths/symlinks, submodule/hook non-execution, size bounds, and exact-byte rehydration.
Manual validation may pin a harmless fixture repository and compare recorded commit/hash to the
source Artifact. **Done** when Core can reopen, retrieve, and verify the exact source Artifact
and its provenance without relying on the external repository still existing.

**OPEN DECISION (M20-B ADR likely):** canonical acquisition format (archive versus manifest of
Artifacts), limits, and acquisition adapter placement. Whatever is selected must retain file
boundaries and an immutable inspected/executed revision.
