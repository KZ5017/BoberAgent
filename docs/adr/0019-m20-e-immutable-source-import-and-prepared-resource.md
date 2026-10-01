# ADR 0019: M20-E immutable source delivery and prepared Resource identity

**Status:** Accepted for M20-E architecture. E1 typed boundary is complete; import/resource behavior has not begun.

## Decision

M20-B's Core-retained raw ZIP and structural manifest are the sole source of preparation
bytes. M20-E introduces a separate, authorized Core→Node Artifact Import primitive behind
the neutral transport. It is not hidden inside `runtime.prepare`, and is not source
materialization or execution. Import is bound to the permit's exact Artifact set and Node,
uses bounded ordered chunks with explicit offsets/resume, verifies declared SHA-256 and size,
rejects conflicting duplicates/identity, and publishes only fully verified bytes. The Node
chooses its managed storage destination; sender-provided paths or names never do. Imported
bytes are not classified as Node-created evidence or queued for normal Node→Core Artifact sync.

The Node materializes the verified archive against the exact structural manifest into a
generated managed workspace. It rechecks path, type, count, depth, size and per-file hashes;
it never invokes unrestricted extraction. Absolute/traversal paths, links, devices, FIFOs,
collisions and manifest/archive drift stop preparation. Source bytes remain immutable and a
partial tree never becomes READY. Publish a read-only source view only after complete
verification. No GitHub re-fetch or source rewrite is allowed.

The prepared Python runtime is a Node-owned `Resource`, identified across boundaries by an
existing `ResourceRef`. A new public PreparedRuntimeRef is not justified. Its workspace is
Resource-owned, not creator-Run-owned, and survives that Run. Physical paths stay Node-private
metadata, not authority. Exclusive preparation/cleanup ownership and a future exclusive or
otherwise safe F lease are required. A Resource is runtime infrastructure, not a Session.

Node produces an immutable, versioned RuntimePreparationManifest Artifact and typed receipt.
Core accepts the receipt only after exact Run/permit/plan/source/Node/Resource binding and
durable Node→Core synchronization plus hash/size verification of the manifest. The manifest
reports observed preparation facts; it is not hardware attestation or a safety certificate.
Core's accepted manifest identity/digest becomes part of a future F handoff.

On interruption, imported or materialized partial state is quarantined or safely discarded;
it is never advertised as a ready Resource. A retry uses a new explicit attempt after cleanup,
except idempotent continuation of a verified chunk import. Exact retained Artifacts may be
reused after identity verification; mutable venvs and writable workspaces are not shared
between distinct preparations. Current Resource availability is projected separately from
historical Core completion.

## Rejected alternatives

- Re-fetching an upstream branch or silently replacing the archived bytes.
- Treating a local Workspace path or SHA-256 digest as public Resource identity.
- Reusing Node→Core Artifact synchronization as a bidirectional repository without import
  admission or provenance distinction.
- Marking a partially extracted tree or venv READY after restart.
- Using a Session merely because preparation is stateful.

## Consequences

E3 needs a dedicated transport-neutral import protocol and Node admission; E4 owns safe
materialization; E5 owns the Resource provider; E6 owns manifest reconciliation. No M20-B
Artifact or acquisition history is rewritten. See [source/workspace design](../m20/M20E_SOURCE_AND_WORKSPACE.md).
