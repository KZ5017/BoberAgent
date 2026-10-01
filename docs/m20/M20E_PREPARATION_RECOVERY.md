# M20-E preparation recovery, reuse and evidence

**Status:** E3 dispatch/import recovery COMPLETE, including real Core↔Kali restart/replay
acceptance; E4–E9 preparation recovery remains future work. This refines
[authority](M20E_RUNTIME_AUTHORITY.md).

E3 persists Core import cursors and Node transfer cursors. A retry opens the same transfer;
the Node returns its durable offset and checks duplicate chunks byte-for-byte. A conflicting
chunk fails. After Node restart, an uncommitted partial file is truncated to the persisted
cursor; it remains unavailable until final hash/size verification. A lost final acknowledgement
is handled by re-verifying the immutable object and returning the same identity. Core restart
loads the existing E2 attempt/reserved RunRef and does not silently create a new Run or
redispatch an uncertain submission. A Core-side transport failure leaves DISPATCHED for
explicit reconciliation; no automatic reroute or PoC retry is introduced. A persisted Core
VERIFIED import is never reopened: identical replay rechecks current E2 applicability and
uses exact Node import status/hash/size to reuse that terminal record. Missing or mismatched
Node proof fails closed. The operator's real acceptance verified both exact imports,
restarted the Kali Node with its original persistent runtime and Node ID, then repeated the
same import successfully against the same Core runtime. The historical 15-minute permit
window still applies; expiry is expected inapplicability, not import corruption. See
[source/workspace](M20E_SOURCE_AND_WORKSPACE.md) for the import boundary.

## Immutable preparation evidence

The Node publishes a versioned, immutable `RuntimePreparationManifest` as a normal Artifact,
with a small typed `RuntimePreparationReceipt` in the Result. The manifest records at least:

| Group | Required evidence |
| --- | --- |
| Identity | schema/profile/version; PreparationRef, RunRef, permit identity/digest, MissionRef, PlanRef and plan intent digest |
| Source | raw/manifest ArtifactRefs, SHA-256, sizes, resolved commit; materialized-tree verification and entrypoint relative path/hash |
| Provider | Node/provider identities and versions, ResourceRef and logical workspace correlation |
| Runtime | trusted interpreter identity, exact CPython version, platform/ABI, runtime fingerprint and venv configuration |
| Dependencies | observed standard-library-only evidence and explicit `external installed dependency set = empty` |
| Controls | preparation budgets and observed usage; ConfinementBackend/profile/version/verified features; fixed environment policy |
| Result | aware timestamps, typed result/failure codes and evidence ArtifactRefs |

No physical workspace path, secret value, raw source, arbitrary provider exception or safety
claim belongs in the typed receipt. Core verifies the receipt's Run/permit/plan/Node/Resource
binding and waits for the manifest Artifact to synchronize and match ref/hash/size and expected
profile before finalizing. The Node reports what it created; Core decides whether that evidence
matches the authorized request. This is not hardware attestation and cannot establish source
safety or execution permission. A Result may arrive before its Artifact.

## Recovery matrix

| Interruption | Required behavior |
| --- | --- |
| Core restart before dispatch | Recover REQUESTED and explicitly re-evaluate current D/Node applicability before first dispatch. |
| Core restart after uncertain dispatch | Reconcile stable RunRef and Node/transport state; do not allocate a second Run or blindly retry. Unprovable work becomes INTERRUPTED. |
| Transport loss | Node continues independently; pending Result/Artifact delivery survives. Reconnect resumes idempotent delivery, not execution. |
| Artifact Import interruption | Partial bytes are unavailable; resume only from verified offset under same permit/import identity or safely restart import. Reverify final hash/size. |
| Node restart during staging or venv creation | Quarantine incomplete workspace/environment. Runtime Resource is not READY; no implicit re-execution. Core reconciles FAILED/INTERRUPTED. |
| Node restart after durable completion | Resource is revalidated for current availability/integrity; historical Core COMPLETED remains unchanged. |
| Lost Result or Artifact acknowledgement | Existing outboxes/redelivery and receiver dedup remain authoritative; no second preparation. |
| Duplicate invocation | Same RunRef and identical fingerprint returns existing state/result; conflicting content is rejected. |
| Cleanup interruption | Persist cleanup state, avoid exposing partials; retry idempotent cleanup separately from Run/Result. |

The Node's existing conservative recovery of unprovable active Runs still applies. E does not
claim to resume an arbitrary Python continuation after restart. A quarantined partial venv is
not trusted or upgraded to READY. A new build is a new explicit preparation attempt only after
safe cleanup; failed/uncertain attempts remain immutable history.

## Reuse and current applicability

A configured trusted interpreter may be reused after baseline verification. Exact retained
raw/manifest bytes may be reused after Artifact identity verification. An identical completed
preparation can be reused only if request/context/permit applicability still match and the
Resource is currently available and integrity-checked. A mutable venv or writable workspace is
never shared between distinct preparations; there is no package cache. Reuse never bypasses
current policy/approval and preparation-admission checks. The current availability projection
may become unavailable while the historical COMPLETED attempt and manifest remain immutable.

The F handoff is the exact PlanRef/intent digest, Node identity, ResourceRef and accepted
manifest identity/digest. F independently rechecks current policy, approval, execution
authorization, Node/provider, exclusive/safe Resource lease, source/entrypoint/runtime
integrity, target scope, network endpoints, F budgets and any separately authorized secret
grants. It derives invocation only from V2 intent; it does not use preparation logs or prose.

In E2, Core reopen restores the immutable request context, reserved RunRef and permit
body/digest without starting work. The provider registry marks persisted providers stale until
a fresh Node handshake; current preparation applicability is false until that refresh. A
changed D policy, exact approval, scope or provider status changes current applicability
without rewriting the historical permit. No E2 recovery path dispatches or automatically
retries a Run.
