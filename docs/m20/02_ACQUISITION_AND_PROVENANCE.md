# M20-B — Immutable acquisition and provenance

## Goal and dependency

Turn **one selected M20-A candidate and one specific historical source hit** into a reproducible
source Artifact. Acquisition is not installation, import, build, or execution. Core verifies the
Mission/hypothesis/candidate/hit relationship before routing a normal bounded acquisition
Capability to an Execution Node. A candidate or hit alone is not executable intent. The accepted
decisions are in [ADR 0014](../adr/0014-m20-acquisition-ownership-and-immutable-source-representation.md).

## Typed boundary

| Input | Output |
| --- | --- |
| Selected `PoCCandidate` and specific historical `ResearchSourceHit`, `MissionRef`, source/repository identity, mutable revision claim, bounded acquisition authorization | Core-owned `PoCAcquisition`, resolved full commit SHA, raw ZIP Artifact with SHA-256/size, versioned structural manifest Artifact, provenance and status |

M20-B v1 accepts public GitHub repository sources only. The Node revalidates repository identity,
resolves the selected historical mutable ref to a **full commit SHA**, and requests a GitHub ZIP
archive by that SHA. The full SHA identifies the upstream snapshot; SHA-256 of the retained raw
ZIP identifies the exact acquired bytes. This is a GitHub archive export, not a complete native
Git checkout. Preserve the ZIP unchanged as the canonical source Artifact and produce a second,
versioned JSON structural-manifest Artifact from it without extraction. The manifest contains
sorted normalized relative POSIX paths, entry types, actual sizes, per-file hashes, and mode/
executable bits where reliable; it does not perform M20-C semantic inspection. Workspace is
Node-local staging, never source identity. Existing Node→Core sync preserves `ArtifactRef`; Core
must report bytes unavailable until the raw ZIP and manifest are durably verified there.

Capture the historical claim and fresh repository-identity check, original and final URI,
resolved SHA and resolution time, retrieval time, raw-byte hash/size, structural inventory, and
acquisition adapter/version. Accept only regular files and directories for M20-C-ready source.
Reject traversal, absolute/drive paths, invalid or colliding names, unsafe depth/length/count/
size/compression, encrypted or unsupported entries, decompression/CRC failure, and all links or
special entries. Reject **all symlinks**; never recurse into submodules or fetch Git LFS objects.
If gitlinks or LFS pointers prevent a supported complete representation, stop as unsupported/
assisted. Unsafe entries are not silently dropped. Enforce explicit bounded download and archive
limits; numeric defaults remain implementation-time choices.

The execution path must consume the pinned Artifact (or a verified materialization of it), never
re-clone a branch or silently refresh dependencies. Recheck content hash after staging and before
execution. If a later revision is desired, create a new acquisition record/Artifact and redo
inspection and validation. This closes the source TOCTOU boundary; mutable external URLs remain
provenance, not execution references.

## Reuse, additions, and non-goals

Reuse SDK Workspace/Artifact APIs, Node spool, existing sync, Core Artifact catalog/storage,
Registry/Router, Run and Result. Add a Core-owned `PoCAcquisition` and a bounded Node acquisition
Capability when M20-B is implemented; neither Core-direct download nor a special transport is
authorized. The Node adapter constructs fixed GitHub destinations and validates every redirect.
The preferred first downloader attempt is a version-constrained managed tool through SDK
`ProcessService`/Tool Registry, but public acquisition is gated on proof of streaming byte,
request, redirect/destination and timeout bounds. If that proof fails, stop for separate review
of a narrow Node-managed fetch SDK service; do not fall back to unrestricted HTTP or shell.

No `setup.py`, install script, build hook, package import, README command, PoC run, or automatic
Knowledge promotion occurs in this phase. No secret material enters the acquisition query or
record.

## Stop, security, and tests

Core persists `PoCAcquisition` separately from the candidate, Run and Artifacts. Its minimal
lifecycle is `REQUESTED → DISPATCHED → AWAITING_ARTIFACT → COMPLETED`, with terminal
`FAILED`/`REJECTED`/`INTERRUPTED` equivalents. Only bounded acquisition input and receipt
cross Core↔Node through existing Contract invocation/result envelopes; research and acquisition
persistence stay Core-private. A successful Result alone does not complete acquisition. Core
validates the selected-source, RunRef and Node binding, resolved identity and typed receipt, then
requires both raw and manifest Artifacts durably verified in Core before completion. Acquisition
does not produce a target-vulnerability Observation or Finding.

Stop on unpinnable revision, repository identity change, hash/inventory inconsistency, redirect
outside allowed destinations, size/path violations, unavailable Artifact content, or ambiguous
source identity. Preserve safe partial evidence and diagnostics without calling it completed.
Same-Run redelivery uses existing deduplication; explicit new attempts retain new history.
Reconcile persisted Result and Artifact availability after restart rather than blindly
redownloading or rerunning an uncertain attempt. M20-C cannot inspect incomplete source.

Tests: mutable branch pinned to a commit, changed upstream content producing a new Artifact,
identical retry idempotency, truncated transfer, Core/Node restart, hash mismatch, malicious
archive paths/symlinks, submodule/hook non-execution, size bounds, and exact-byte rehydration.
Manual validation may pin a harmless fixture repository and compare recorded commit/hash to the
source Artifact. **Done** when Core can reopen, retrieve, and verify the exact source Artifact
and its provenance without relying on the external repository still existing.

The accepted decisions are recorded in [ADR 0014](../adr/0014-m20-acquisition-ownership-and-immutable-source-representation.md).
Implement in order: **B1** Core record/selected-hit lookup/typed boundary/definition without
public network; **B2** local fixtures, downloader proof and hostile ZIP inventory; **B3** raw/
manifest Artifact sync and restart-safe finalization; **B4** bounded GitHub identity/SHA/archive
adapter with mocked network tests; **B5** opt-in public-repository provenance/reopen smoke,
stopping at acquired evidence. Exact numeric limits and downloader/version remain implementation
choices. M20-C semantic inspection, M20-D policy/plan, M20-E/F runtime/staging, and private,
submodule or LFS acquisition remain deferred.
