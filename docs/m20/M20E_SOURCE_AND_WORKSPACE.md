# M20-E exact source import, materialization and workspace

**Status:** E3 opaque import COMPLETE (real Core↔Kali acceptance PASSED); E4
materialization/workspace NOT STARTED. See
[ADR 0019](../adr/0019-m20-e-immutable-source-import-and-prepared-resource.md).

`preparation-import-v1` uses a stable permit+Artifact import ID, explicit byte offsets,
bounded (at most 1 MiB) chunks, per-chunk SHA-256, start/status/finalize and authenticated
Core principal. The Node checks the permit's exact ArtifactRef/hash/size and E1 import/temporary
budgets before accepting bytes. Partial files live only in the Node's managed
`imported-inputs/partial` area; complete SHA-256/size-verified bytes are atomically published
under `imported-inputs/objects`. No caller supplies a destination path. Published identities
are not Node-produced evidence and are never queued for Node→Core Artifact sync. Existing
exact content can be reused only after current authority and on-disk hash/size verification.
E3 does not extract or semantically inspect the raw archive or manifest.

## Exact retained source

The completed M20-B `PoCAcquisition` identifies one raw GitHub ZIP Artifact and its structural
manifest Artifact, their refs, SHA-256, sizes and resolved full commit. E must use these exact
Core-retained bytes, not a fresh GitHub fetch, README command, branch name or recompressed ZIP.
Core checks content availability and permit pins before sending. Importing an Artifact is
infrastructure; importing it does not assert that it is safe to materialize or execute.

## Core→Node Artifact Import

This is a new neutral transfer direction, distinct from existing Node→Core evidence sync.
Core is sender; Node is receiver. A preparation permit authorizes an exact two-Artifact set on
one Node and binds an allocated preparation RunRef. Core may import after permit issuance and
Node admission, before dispatching that Run through the normal Router; the later capability
invocation rechecks the same permit. This avoids inventing an initial WAITING_RESOURCE state.
A versioned import opening identifies ArtifactRef, hash, size, permit/import identity
and bounded limits; data uses bounded byte chunks with explicit offsets and sequence/identity;
finalize verifies actual size and SHA-256 and atomically publishes Node-managed bytes. The Node
must reject missing, overlapping/conflicting, out-of-order or oversized chunks unless an
explicitly verified resume cursor permits replay; identical replay is idempotent. Interrupted
imports retain safe temporary state or restart from zero after validation. No partial bytes
appear as ready. No sender path, archive name or workspace path chooses storage location.

The import store distinguishes `IMPORTED_SOURCE` from locally produced spool evidence. Imported
bytes must not enter the Node→Core sync queue as new Node evidence. Identity collision with a
different digest or size fails without replacing content. Permit, Node and Artifact binding are
checked both when opening and finalizing; disconnect and restart do not bypass admission. The
protocol changes are explicitly deferred to E3 and belong in the shared neutral transport,
not Core/Node models or MCP-specific domain types.

## Materialization

Only after both imports verify may the Node materialize. It allocates a generated managed
workspace rooted under its configured directory; no caller-controlled physical path. It
parses the retained ZIP and manifest with bounded entry count, depth, names, uncompressed
total/per-file bytes and compression ratio. It writes regular files/directories only, never
unrestricted `extract()`. Absolute/drive/traversal paths, symlinks, hardlinks, devices/FIFOs,
ambiguous separators, duplicate/case/Unicode collisions and unexpected manifest entries fail
closed. Each extracted file's size/hash and the complete tree are reconciled against the
retained structural manifest. Staging occurs in a private temporary tree; the source view is
published read-only only after all checks. Failure quarantines/removes partial state, never
marks a Resource READY. Source bytes are not patched, imported, compiled or run in E.

## Ownership and identity

The fresh Python environment and its workspace belong to the prepared Node `ResourceRef`,
not to the creator Run. They can survive that Run and a Node restart if reverified. The
Resource owns exclusive preparation/cleanup; F later requires an explicit safe lease.
ResourceRef is the logical cross-boundary handle. Workspace identity is a local correlation;
the physical path remains Node-private. A Session represents stateful interaction, not this
runtime infrastructure. Distinct attempts do not share mutable venvs or writable workspaces.
Exact retained source bytes may be reused only after identity verification. No package cache
is part of baseline E.

Node emits a typed receipt and immutable RuntimePreparationManifest Artifact after verified
preparation. The receipt identifies Run, permit, plan/source, Node/provider, Resource and
manifest ref/hash/size; it cannot by itself prove successful Core receipt. Core waits for
normal Node→Core Artifact synchronization and verifies the manifest before COMPLETED.
