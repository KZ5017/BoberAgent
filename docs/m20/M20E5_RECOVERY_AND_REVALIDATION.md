# M20-E5 recovery, expiry and failure classification

**E5-B metadata recovery COMPLETE; E5-C CLOSED; E5-D full distribution revalidation implemented offline; constructed-runtime revalidation NOT STARTED.** Parent: [E5 architecture](M20E5_ARCHITECTURE.md).
Historical evidence, current integrity, authority and execution readiness are separate.

## Implemented E5-B recovery boundary

Node initialization allocates a fresh logical startup generation and invokes the SQLite
Resource repository's metadata-only `reconcile`. Untouched RESERVED metadata remains
RESERVED. An active owner from another generation or past lease expiry, or abandoned BUILDING
metadata without an owner, is quarantined conservatively. Historical ResourceRef/request
pins remain; no replacement Resource, constructor replay or positive verification occurs.
Remaining reservations become fully spent accounting entries; the ledger is never reset.
An interrupted cleanup stays inspectable CLOSING/QUARANTINED/FAILED, and a new explicit
Node-owned exclusive cleanup claim may finish the metadata-only teardown. CLOSED/REMOVED
and lost-acknowledgement completion replay retain the same identity/history.

There are no E5-B files, processes, cgroups or mounts to reconcile. The runtime matrix below
remains a requirement for later construction/revalidation slices, not an implemented live
cleanup claim. New preparation claims and BUILDING/budget mutations require an unexpired
admitted permit; historical queries and trusted Node-owned quarantine/cleanup do not renew it.

## Recovery and change matrix

E5-C adds independent bounded supervisor/guardian teardown and the Node-only journal in
migration `0009_runtime_confinement`. On the same Linux boot, safety recovery addresses
only the exact logical operation's group under the pinned delegated parent, proves it empty
and records interruption. Changed delegation fails closed. After reboot, old work is interrupted
without killing possibly reused groups/PIDs. Terminal evidence never reopens. Node startup
performs safety reconciliation only; active probes are explicit. Missing recovery configuration
is surfaced as degraded, not successful cleanup. Shutdown waits for owned operation finalization.
See [implemented boundary and pending real acceptance](M20E5C_IMPLEMENTATION.md).

| Event | Required action before any reuse |
| --- | --- |
| Core restart | Existing attempt/permit/Run/Resource correlation; current applicability, then explicit status/revalidation. No redispatch/new identity on uncertain acknowledgement. |
| Node restart with RESERVED/BUILDING/VERIFYING | Reconcile exact owned supervisor/cgroup, kill surviving descendants, quarantine partial files; interruption is terminal for this build. No constructor replay. |
| Node restart with PUBLISHED/READY | UNCHECKED current validity; verify binding, exact source and environment inventories, trusted closure, backend profile/limits, empty old group and current authority. Only then current VALID. |
| Host reboot | Old process handles invalid; identify changed boot, verify no surviving owned work; retained bytes may be revalidated with current authority. Never treat old probe timestamp as current proof. |
| Interpreter/stdlib/loader or bwrap update | Fingerprint mismatch denies old Resource reuse. Preserve evidence; no in-place upgrade. New explicit attempt after safe cleanup. |
| Kernel update | Previous enforcement proof stale. Current trusted probes must pass the same profile and append evidence; do not overwrite historical proof. Unsupported behavior fails closed. |
| Runtime file/config/link mutation | Integrity failure, LOST/quarantine; no repair from source or installer. |
| E4 tree mutation/missing source | Existing E4 verification fails; dependent Resource unusable. Do not rebuild source or change source pins. |
| Permit expiry or D/policy/approval/provider change | Current preparation applicability denied; bytes/history may remain. No automatic permit renewal/rebinding. |
| Disconnect while constructing | Node supervisor/ledger continue independently within existing authority/deadline. Reconnect queries same operation; no duplicate constructor. |
| Cancellation/timeout/limit hit | Kill owned tree, await empty group, quarantine, typed failure. No READY even if venv files look complete. |
| Storage rename before DB commit / evidence failure | Quarantine orphan publication; missing evidence cannot be inferred from files. |
| Release interruption | Durable cleanup cursor, repeat exact owned teardown safely; never remove unrelated/shared source. |

E5 local foundations must cover these runtime cases. E7 still owns the larger cross-component
E recovery acceptance; implementing local safety does not mark E7 complete.

## Permit expiry and cleanup

E2 currently issues fifteen-minute permits; E1 allows a bounded validity interval. E5 does
not extend it. At each mutating/verification operation require Core current applicability
and Node permit time/bindings/actions. Supervisor deadline is no later than permit expiry,
remaining aggregate budget and per-operation timeout. Reserve time for fail-safe teardown;
expiration while constructing stops work and cannot produce READY afterwards.

After expiry:

- Read-only historical metadata/evidence inspection is allowed; it never returns a usable
  handle merely because READY was once persisted.
- Passive Node integrity/owned-state inspection is maintenance, not fresh preparation proof.
- Interpreter probes, runtime revalidation for reuse, mutation, creation and reuse under that
  permit are denied. A previous successful revalidation is not a renewable lease.
- Byte retention is allowed by local retention policy. Do not delete evidence solely because
  its permit expired, nor retain an unbounded temporary mount indefinitely.
- Safety teardown/quarantine belongs to Node ownership of the previously admitted operation.
  It remains possible after expiry without granting new target/preparation action. The Node
  maintenance path may kill its own processes and clean exact owned scratch/Resource state;
  it cannot accept an expired caller request as new authority or delete arbitrary paths.
- A new construction attempt needs explicit Core admission and a new immutable binding;
  no transfer of an old venv to a new permit. Future F authorization, not implemented here,
  may define its own current verification of retained prepared evidence; E5 does not do so.

Core Run cancellation and Resource lifetime are distinct: cancellation stops an active
constructor and prevents successful publication. An already prepared immutable Resource may
outlive its creating Run. Resource release is explicit owned lifecycle work, not Run completion
or Session closure. Durable lease/operation generation prevents cleanup racing construction;
evidence/history persists after bytes are removed.

## Revalidation algorithm

The following complete constructed-environment algorithm remains future E5 work. E5-D
currently implements full fresh static distribution rehash/comparison only, with current
root/trust/schema pins. It never marks a Resource VALID/READY. Immutable provenance survives
reopen; an interrupted inspect claim is quarantined, never completed by recovery. See
[E5-D implementation](M20E5D_IMPLEMENTATION.md#evidence-accounting-and-durability).

1. Revalidate current Core D applicability before sending the typed request. Node checks
   principal, permit/digest/time, exact Run/Node/provider/Resource/spec binding and allowed
   actions; it does not decide Core policy.
2. Exclusively claim the exact existing Resource without resetting spent budget. Reject
   in-progress, failed, lost, closed or differently bound builds. Reconcile old process tree.
3. Rehash E4 files through its existing verifier and validate the entire published venv
   inventory with no-follow confined traversal. Compare all pinned tool/runtime identities.
4. Under fresh full confinement, execute only fixed trusted environment verification/probes.
   No source is imported or mounted writable. Observe all remaining budgets/expiry.
5. Append current verification evidence and update current-validity generation. Return the
   same ResourceRef and original construction evidence; do not replace its immutable manifest.
   Any uncertainty denies use. No automatic repair/rebuild, install or source refetch.

## Typed failures

Keep existing `PreparationReasonCode`/category semantics at the E1 envelope boundary.
Introduce the following closed **provider detail codes** only where the current broad code
cannot explain an actionable failure. They are not new domain success states or arbitrary
exception text. Future typed evidence/transport can carry the detail beside the existing code.

| Class | Existing E1 code | E5 detail / behavior |
| --- | --- | --- |
| Authority | PREPARATION_NOT_AUTHORIZED / AUTHORITY_STALE / POLICY_DENIED / APPROVAL_INAPPLICABLE | Wrong binding/action/principal, expired permit or changed context: reject before construction |
| Host prerequisite | RUNTIME_UNAVAILABLE / NODE_CAPABILITY_MISMATCH | PYTHON_RUNTIME_UNAVAILABLE, PYTHON_RUNTIME_MISMATCH; missing/wrong trusted 3.12 closure |
| Host enforcement | CONFINEMENT_UNAVAILABLE | PROCESS_LIMIT_UNAVAILABLE, MEMORY_LIMIT_UNAVAILABLE, STORAGE_LIMIT_UNAVAILABLE, DESCENDANT_CONTAINMENT_UNAVAILABLE, RUNTIME_LIMIT_UNAVAILABLE |
| Unsupported | DEPENDENCY_POLICY_DENIED / BUILD_UNSUPPORTED / SECRET_REQUIREMENT_UNSUPPORTED | DEPENDENCY_INSTALL_FORBIDDEN; no fallback install, privilege or Secret request |
| Construction | RUNTIME_UNAVAILABLE | VENV_CREATION_FAILED; retain bounded phase/exit detail, quarantine, no READY |
| Integrity | PREPARED_CONTENT_MISMATCH / SOURCE_INTEGRITY_FAILURE / MANIFEST_MISMATCH | RUNTIME_INTEGRITY_FAILURE, RUNTIME_IDENTITY_CONFLICT, RUNTIME_REVALIDATION_FAILED; preserve original evidence |
| Budget/storage | WORKSPACE_LIMIT_EXCEEDED / PREPARATION_TIMEOUT / STORAGE_UNAVAILABLE | Explicit violated limit/mechanism; kill group and quarantine |
| Recovery | PREPARATION_INTERRUPTED | RUNTIME_QUARANTINED or ambiguous constructor termination; never infer success |
| Cancellation | PREPARATION_CANCELLED | Stop and verify all descendants before teardown finishes |

Logical-state integrity conflicts are not capability NEGATIVE assessments. Transport loss is
not runtime failure by itself. Bound diagnostics, preserve operational refs, and omit secrets,
caller environment, raw source or private host paths. No suppression of unknown measurement,
missing proof or failed cleanup to make a success record validate.
