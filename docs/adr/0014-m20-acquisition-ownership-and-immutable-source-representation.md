# ADR 0014: M20 acquisition ownership and immutable source representation

**Status:** Accepted; M20-B1 foundation and fixture-only M20-B2 implemented, M20-B3–B5 pending.

## Context

M20-A retains a Core-owned `PoCCandidate` as a historical research lead. Its individual
`ResearchSourceHit` rows preserve provider claims, including a mutable GitHub `branch:<name>`
claim. Neither a candidate URL nor a branch name identifies bytes that may safely be inspected
later. The current Node can create Artifacts in managed Workspaces and synchronize their bytes to
Core; Core→Node Artifact transfer does not exist. M20-B must bind one selected hit to an immutable
source representation without executing repository-controlled code or starting M20-C inspection.

## Decision

### Ownership and selection

Core owns Mission authorization, the selected `VulnerabilityHypothesisRef`, `PoCCandidateRef` and
**specific historical `ResearchSourceHit`**, a durable `PoCAcquisition` decision/lifecycle,
limits, routing, finalization, and provenance. Selection never means “latest hit” or “current
default branch.” M20-B implementation adds a narrow lookup that verifies the selected hit belongs
to the candidate, hypothesis, and Mission. Historical research rows are not rewritten.

Acquisition is one normal bounded Capability operation, dispatched through the existing Core
Capability Registry/Router, `CapabilityInvocation`/`CapabilityRun`, neutral transport, and Node
Capability Runtime. The Execution Node owns fresh repository-identity checking, mutable-ref
resolution, bounded retrieval, Workspace staging, structural inventory, and Artifact spooling.
Core does not download source or import the acquisition implementation.

### Immutable source identity and representation

M20-B v1 accepts public GitHub repository sources only. On the Node, the selected historical
branch/ref is resolved to a **full commit SHA** after fresh repository-identity validation. The
Node requests one GitHub **ZIP archive addressed by that full SHA**, never by a mutable branch,
tag name alone, or default branch. The full commit SHA is the upstream snapshot identity;
SHA-256 of the retained raw ZIP is the exact acquired-byte identity. Record the requested
mutable ref, resolved SHA, resolution time and source endpoint, fresh repository identity,
redirect/final URI, and adapter/version. A GitHub ZIP is described as a **GitHub archive export
of commit `<SHA>`**, not a complete native Git checkout. GitHub may regenerate an archive with
different compression bytes; never replace an existing acquired Artifact by re-fetching it.

The unmodified raw ZIP is the canonical source Artifact. A managed Workspace is temporary
Node-local staging, not source identity. Existing Node→Core Artifact synchronization publishes
verified bytes with the same `ArtifactRef`; no Core→Node transfer is added. M20-C may inspect the
verified Core-side Artifact. Cross-node staging for M20-E is deferred, and no later stage may
substitute a fresh upstream download for retained bytes. Recheck the retained hash whenever
source is materialized for inspection or execution.

### Structural inventory and hostile-source handling

Produce a deterministic, versioned file manifest from the retained ZIP **without filesystem
extraction**. Prefer a second JSON Artifact associated with the same acquisition. It records
sorted normalized relative POSIX paths, entry types, actual uncompressed sizes, per-file SHA-256,
mode/executable bit when reliably represented, archive root prefix, and representation version.
It records structure only, not entrypoint, dependencies, exploit behavior, target effects, or
execution suitability.

A source becomes M20-C-ready only when its archive contains regular files and directories and
passes bounded validation. Reject absolute/drive paths, traversal, ambiguous separators,
invalid/NUL names, duplicate or case/Unicode-normalization-colliding paths, unsafe path depth or
length, excessive counts/sizes/compression ratios, encrypted or unsupported compression,
CRC/decompression failures, and all links, devices, FIFOs and other special entries. **All
symlinks are rejected**; none are followed or materialized. Gitlinks/submodules stop automatic
completion; no submodule recursion occurs. No secondary Git LFS request is made. If LFS pointer
or related semantics mean the retained export is not a supported complete representation, stop
as unsupported/assisted. Unsafe entries are never silently omitted to claim success. A raw
Artifact may remain as evidence after rejection, but it is not a completed source or manifest.

Enforce explicit bounds on downloaded/archive bytes, actual uncompressed total and single-file
bytes, file count, path depth/length, compression ratio, redirects, outbound request count,
allowed destinations, and timeout. Exact numeric defaults are implementation-time decisions;
the existence and actual enforcement of these limits are not deferred.

### Egress and downloader gate

The trusted Node adapter constructs fixed GitHub API/archive destinations; untrusted candidate
text, README, and repository content are never arbitrary URLs to fetch. HTTPS destinations and
each redirect are validated against the narrow host/endpoint set needed for identity resolution
and SHA-addressed archive retrieval. No private-repository acquisition or token delivery is
part of v1.

The preferred first implementation attempt uses a **version-constrained trusted downloader**
through SDK `ProcessService` and the Node Tool Registry: argument vector only, no shell, no
automatic redirects, explicitly checked `Location`, bounded requests/bytes/time, and no ambient
configuration or proxy behavior unless explicitly authorized. **This choice is conditional.**
Before any public acquisition, tests must prove that the selected downloader/version enforces
streaming byte limits, destination/redirect restrictions, timeout, and request bounds. If not,
stop and review a narrow Node-managed fetch SDK service separately. Do not fall back to an
unrestricted HTTP client, shell, or arbitrary-URL downloader. This ADR does not select the
executable or version.

### Durable acquisition and finalization

`PoCAcquisition` is Core-owned and separate from candidate, Artifact, and CapabilityRun. It
retains the Mission/hypothesis/candidate/selected-hit relationship; historical and freshly
checked source identity; mutable claim and full resolved SHA; resolution/retrieval provenance;
adapter/version; selected Node/provider and RunRef; raw ZIP and manifest ArtifactRefs/hashes/
sizes; timestamps; status; and safe diagnostic. It never stores tokens, source bytes, arbitrary
provider response bodies, or Workspace paths. Exact fields and schema are M20-B implementation
details.

The minimal Core lifecycle is `REQUESTED → DISPATCHED → AWAITING_ARTIFACT → COMPLETED`, with
terminal `FAILED`, `REJECTED`, and `INTERRUPTED` equivalents. Node Run state already covers local
resolving/acquiring progress; duplicate Core states are not required. A successful
`CapabilityResult` alone does not complete acquisition. Core validates the typed acquisition
receipt, RunRef/Node/selected-source binding, resolved identity and Artifact descriptors, then
waits for **both** source and manifest to be durably verified and available in Core before
completion. Acquisition emits no target-vulnerability Observation or Finding.

Only bounded input/receipt data that crosses Core↔Node belongs in shared Contracts, carried by
the existing invocation/result envelopes. `PoCAcquisition`, `ResearchAttempt`, `PoCCandidate`,
and `ResearchSourceHit` persistence remain Core-private. No acquisition-specific transport
protocol is introduced.

The same request/RunRef uses existing invocation deduplication. A new explicit attempt has new
history; it may reuse an already verified Artifact for the exact selected source/revision where
appropriate, but must not overwrite prior acquisition records. Candidate+commit is not an
acquisition ID. If Core crashes after receiving a Result or Artifacts, finalization replays from
the durable Run/result/catalog without redownloading. Existing Node recovery conservatively
fails unprovable running Runs, and existing Artifact sync resumes partial byte delivery. Neither
an incomplete download nor incomplete sync can become `COMPLETED`; no uncertain attempt is
blindly rerun with a new RunRef.

An upstream branch HEAD change is captured as a newly resolved SHA in an explicit attempt while
preserving the historical claim. Never switch silently to a different default branch, owner,
repository identity, or alias. Deleted/private/unresolvable sources fail. Rename, transfer, or
identity mismatch stops for explicit reselection rather than an automatic redirect.

## Consequences and security invariants

- Source provenance and exact bytes survive a Core restart independently of upstream GitHub.
- Artifact content may arrive after the terminal Result; Core reports `AWAITING_ARTIFACT` rather
  than pretending that a descriptor makes bytes available.
- A Workspace path, URL, mutable ref, repository update time, or commit SHA alone is not the
  acquired-byte identity. The raw Artifact hash is retained and checked at later use.
- Acquisition executes **zero repository-controlled code**: no checkout hook/filter,
  submodule/LFS hydration, package import/install, README command, build, or PoC execution.
- No source-specific result is treated as World State proof or execution authorization.

## Rejected alternatives

- Core-direct acquisition, a special acquisition transport, or a shared filesystem bypass the
  established Core/Node ownership and Router/Artifact paths.
- Workspace-as-canonical-source and mutable branch/tag-as-source-identity cannot preserve an
  immutable cross-restart byte identity.
- Initial git clone/fetch, file-by-file Contents API, tarball format, recursive submodule or
  automatic Git LFS acquisition expand behavior and attack surface beyond the one bounded v1
  representation.
- Silently following repository redirects, renames, owner transfers, or a new default branch
  changes the selected historical lead.
- Normalizing/rebuilding the ZIP in place destroys raw-byte provenance. A generic arbitrary-URL
  downloader or unrestricted HTTP client evades the bounded egress decision.

## Deferred decisions

M20-B implementation chooses measured numeric defaults, the exact downloader/version and its
proof, and manifest serialization details. A narrow fetch SDK service requires a separate
review **only if** the preferred managed-tool proof fails. M20-C owns semantic inspection;
M20-D owns ExecutionPlan source-hash/policy decisions; M20-E/F own Core→Node staging, runtime
isolation and execution; later work owns private-repository authentication, submodule and LFS
acquisition. None is authorized by this ADR.

## Implementation order

1. **M20-B1:** Core acquisition domain/persistence, selected-hit lookup, shared input/receipt
   boundary, static Capability definition; no public network.
2. **M20-B2:** deterministic local fixture, downloader feasibility proof, structural ZIP
   inventory and hostile fixtures; no public GitHub acquisition.
3. **M20-B3:** raw/manifest Artifacts, Node→Core sync, Core finalization and restart reconciliation.
4. **M20-B4:** fresh GitHub identity validation, branch→full-SHA resolution, fixed-host
   SHA-addressed ZIP acquisition and mocked-network tests.
5. **M20-B5:** separately opted-in public-repository provenance/hash/reopen smoke; stop at the
   acquired Artifact.

M20-B remains one milestone. This ADR does not implement any phase.
