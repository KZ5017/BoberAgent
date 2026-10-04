# M20-E5 Resource, evidence and typed boundary

**Architecture specified; E5-A COMPLETE; E5-B–H NOT STARTED.** Parent: [E5 architecture](M20E5_ARCHITECTURE.md).

## Identity, ownership and storage roles

Use existing `ResourceRef` and `ResourceDescriptor`, `resource_type=python_runtime`,
`provider=python-stdlib@1`, Mission ownership and the admitted preparation Run as creator.
Workspace ownership is the ResourceRef; preparation/permit/plan bindings belong in typed
provider detail. Core owns the attempt and applicability; Node owns bytes/lifecycle/leases.
Neither an absolute path, cgroup name, PID, venv prefix nor evidence hash is authority.

Reserve a generated ResourceRef once in a transaction with unique preparation and permit
bindings. Identical requests return that same ref; conflicts reject, never replace a row.
A content-addressed ref would incorrectly imply reuse across Missions/permits; deterministic
refs add no benefit over the existing transactional identity convention. A separate immutable
binding digest **does** include:

- PreparationRef, permit ref/digest, RunRef, MissionRef, PlanRef/intent digest;
- Node ID, admitted capability provider identity/version;
- E4 materialization ID, tree digest, entrypoint digest and exact source Artifact pins;
- preparation/runtime profile ID/version/digest and authorized budgets/actions;
- interpreter runtime fingerprint, backend/profile identity/version;
- Python construction implementation version and selected fixed layout version.

The reservation stores request bindings first. Verified interpreter/backend evidence seals
the complete binding before construction; no later field may be silently upgraded. Changed
content, interpreter or implementation cannot reuse the same Resource as a different runtime.

| Object | Writable? | Durability / identity |
| --- | --- | --- |
| E4 PUBLISHED source | Never by E5; only existing owned quarantine/cleanup on failure | Existing materialization identity/receipt, unchanged |
| Construction scratch | Closed provider only, bounded; never source-owned | Ephemeral mount, logical workspace/operation association |
| Published venv | Read-only when sealed, no caller mutation | Resource-owned persistent directory and verified inventory |
| Runtime evidence | Append-only | Typed digest and ordinary evidence Artifact identity |
| Future execution cwd/temp | Not created in E5 | F must allocate under its own authority/budgets |

E5 does not reparent or edit the E4 source record. It holds a durable reference/retention
dependency so source cleanup cannot remove it while a live Resource depends on it.
No automatic workspace deletion when the preparation coroutine or creating Run ends.

## Lifecycle and availability

Reuse `ResourceRuntimeState`: CREATING → READY; failed construction → FAILED;
lost/unverifiable runtime → LOST; owned teardown → CLOSING → CLOSED. CLOSED never reopens.
FAILED/LOST do not transition back to READY under the same construction attempt. Quarantine
is retained-content disposition with a reason, not another global Resource enum.

Provider phases are durable `RESERVED`, `BUILDING`, `VERIFYING`, `PUBLISHED`, `QUARANTINED`,
`REMOVED`. These explain progress; they do not compete with Resource state. Persist every
boundary that distinguishes recovery actions. No externally visible READY until files,
inventory/evidence and DB publication are durable. Atomic filesystem rename precedes the DB
READY commit; an orphan rename after crash is quarantined, not inferred successful.

Current validity is a separate projection: `UNCHECKED`, `VALID`, `INVALID`, with checked time
and Node boot/start generation. Persisted READY alone cannot satisfy `get_usable` or a lease.
On restart READY starts UNCHECKED; a successful exact revalidation changes only this projection
and appends evidence, not historical construction. Corruption changes current state to LOST
and quarantines. Missing limits/current authority denies use without falsifying history.

Construction, revalidation and cleanup take an exclusive lease backed by transactional
ownership/generation plus process supervision, not an immortal coroutine or stale boolean.
Read-only metadata inspection may be shared. No generic Resource acquisition yields an argv
executor, local path, Session driver or future F launch right. No generic `resources.create`
with arbitrary config may bypass the preparation gate. F's exclusive execution lease is
not implemented in E5.

## Immutable E5 evidence

Specify a versioned **`PythonRuntimeEvidence-v1`**, not a second final preparation manifest.
Shared semantic evidence types belong in Contracts when exchanged; private host paths,
mount/cgroup handles and launch internals remain Node-only. The record includes:

| Group | Required fields |
| --- | --- |
| Binding | All sealed binding fields above, ResourceRef, logical workspace ID, evidence schema/digest |
| Interpreter | Registry tool key, executable hash, CPython exact version/build, platform/architecture, ABI/SOABI/cache tag, base-prefix/stdlib logical layout and closure fingerprint |
| Environment | Stable in-sandbox venv prefix, pyvenv.cfg/inventory digest, copied executable identity, permitted relative links, system-site-packages false, no pip bootstrap/use, external installed set empty |
| Non-actions | Source import/compile/entrypoint false, package install false, no activation script, Secret grant set empty, preparation network NONE |
| Enforcement | Backend binary/version and profile digest, kernel/boot generation, all twelve features, actual mechanisms/effective limits, probe outcomes, cgroup counters, storage allocation caps, descendant-empty proof |
| Usage | Aggregate preparation usage and E5 deltas, budget ledger correlation, output size/hashes, no invented zero for an unmeasured field |
| Result | Start/end UTC times, monotonic duration, implementation version, verification outcome and typed reasons, evidence ArtifactRefs |

No source bytes, target secrets, arbitrary exception dumps or private host paths in evidence.
Stable namespace paths are layout facts only, never authority. Keep inventory size bounded;
larger inventory/probe records use normal immutable Artifacts, not oversized transport payloads.

E6 composes the existing `RuntimePreparationManifest-v1`: ResourceRef, interpreter/environment
summaries, E4 materialization, aggregate usage and all features, plus the E5 evidence Artifact
in `evidence_artifact_refs`. E5 must not fabricate a `RuntimePreparationReceipt`, complete the
Core attempt or a terminal success Result to make intermediate evidence deliverable. Exact
E4 transport evidence is mapped explicitly to the final Contract materialization summary;
the similarly named types are not interchangeable.

## Future persistence, not migrations in this task

Reuse the existing Node Resource/workspace/process infrastructure. One provider-detail row
keyed by ResourceRef records unique preparation/permit binding, construction phase, immutable
evidence identity, private storage key, cleanup cursor and current verification projection.
An append-only verification record preserves repeated revalidation/failure evidence. Persist
the attempt-owned cgroup/supervisor operation identity and cumulative budget ledger so Node
restart cannot reset usage. Extend owned process metadata narrowly if its current direct-child
record cannot represent the closed supervised operation; do not build a second generic runner.

Concurrent same-binding requests join/return the existing state; no second builder. Different
bindings fail explicitly. Use filesystem exclusivity as well as a DB claim; never assume a
stale SQLite lease proves a previous process stopped. Inspect/kill the exact owned group first.

No new Core table is required by E5: Core retains its attempt, permit and existing routed Run.
Final Resource/evidence acceptance remains E6 using existing reserved fields where sufficient.
Future Node schema changes are forward migrations only, preserving browser/listener and E3/E4
state. There is no migration or schema change in this architecture task.

## Provider and neutral transport

Introduce Node-owned **`PythonRuntimeProvider`**, not an unrestricted runtime plugin framework.
Inputs are a locally validated admission handle for the existing permit/Run, exact E4 published
source binding, Tool Registry entry, budgets and cancellation/deadline. Public request data is
never that trusted handle. Outputs are Resource descriptor, typed progress/failure and evidence.
Closed methods: `inspect_interpreter`, `create_empty_environment`, `verify_environment`,
`revalidate`, `release`; no source command or arbitrary argv parameter.

The existing E3 Core dispatch service rechecks current D applicability before neutral
`CHECK_RUNTIME`, `PREPARE_RUNTIME`, `RUNTIME_STATUS`, `REVALIDATE_RUNTIME` requests. Keep
the same admitted `runtime.prepare` Run and authenticated Core principal. Each envelope pins
protocol version/message ID, Node/preparation/permit/digest/Run; operations referring to a
Resource also pin ResourceRef and immutable binding digest. Node independently validates the
matching authority/actions/time, local source and provider. CHECK may run closed disposable
probes only under current authority; STATUS returns metadata and never grants use.

PREPARE durably accepts the operation and returns current state/correlation; status polling
is separate from completion. A lost connection/ack must not spawn another builder or cancel
the Node-owned work. Repeated identical delivery is idempotent, conflicting delivery rejects.
E5 does not mint a new Run, dispatch directly around Router, or terminally finalize the E3 Run.
Persist provider-operation progress while that preparation Run remains admitted; E6 owns its
terminal lifecycle integration.

`RELEASE_RUNTIME` is an idempotent owned cleanup request, never general filesystem access.
While authority is current, validate its cleanup action. After expiry, only the separate
Node-owned maintenance/cancellation path described in [recovery](M20E5_RECOVERY_AND_REVALIDATION.md)
may clean; an expired caller permit must not become a fresh release authorization.
Transport owns envelopes only. No host path, shell, Python text, environment injection or
package URL input. In-memory and MCP adapters carry the same neutral messages. The future
capability continues to consume SDK `RuntimePreparationService`; it cannot import this provider.

## E5-A implemented boundary

`boberagent_contracts.python_runtime` provides frozen, strict E5 models without a runtime
implementation or authority issuer:

- `PythonRuntimeRequestBinding` composes the existing E1 spec (exact source, provider,
  profile, budgets/actions) with permit/digest/Run and E4 materialization/tree/entrypoint.
  No interpreter facts are fabricated at reservation. `PythonRuntimeAuthorityProjection`
  cross-checks against the existing permit. Consistent serialization is **not** authentication,
  current applicability or a trusted Node admission handle.
- `PythonRuntimeBinding` seals ResourceRef, request, interpreter and backend identity.
  It contains no readiness, validity or authorization. Schema layout labels are
  `m20-e5-python-layout@1`, `m20-e5-system-python@1`, `m20-e5-system-stdlib@1`;
  construction version is `python-stdlib@1`. None is a host path or host-support claim.
- `PythonResourceState` mirrors the existing Node Resource vocabulary. Provider phase and
  checked validity are separate. Decoding READY creates no Resource and grants no use/launch.
- `PythonRuntimeEvidence-v1` is intermediate historical evidence: typed inventory,
  interpreter/closure hashes, non-actions, all twelve mechanism/probe claims, effective
  caps/counters, measured usage, outputs, UTC timestamps and evidence ArtifactRefs.
  VERIFIED requires complete evidence within budgets; rejected evidence needs typed reasons.
  Validation proves no live host facts and does not complete the E6 final receipt.
- `PythonRuntimeReason` adds narrow failure detail mapped to existing E1 reason codes;
  authority/resource/cancellation reasons are reused, not replaced by generic FAILED.

Canonical request/binding/evidence SHA-256 helpers reuse the existing canonical serializer.
All meaningful pins participate; declared sets canonicalize independently of order. Unknown
profiles/versions/fields and host-path-shaped identities reject. The profile remains CPython
3.12, dependency-empty and network/Secret-denied. Private handles never cross this boundary.

`boberagent_transport.preparation_runtime` defines independent `preparation-runtime-v1`
requests and tagged accepted/rejected responses. The five operations are CHECK_RUNTIME,
PREPARE_RUNTIME, RUNTIME_STATUS, REVALIDATE_RUNTIME and RELEASE_RUNTIME. Resource operations
pin ResourceRef and sealed binding digest. Stable message identity includes request digest,
operation and Resource pins, excluding delivery timestamp. Responses cross-check evidence
and state correlation. No endpoint, dispatcher, Node handler or MCP wiring exists; E3/E4
versions remain unchanged. Future admission must independently authenticate/recheck current
authority, exact E4 state and Resource ownership. These models perform no lookup or expiry gate.

SDK `RuntimePreparationService` remains unchanged: its final receipt belongs to E6. No
`ctx.resources.prepare_runtime` is added. Generic fake `resources.create(python_runtime)`
explicitly denies; production Node generic dispatch already rejects this type. No fake
pretends to construct runtime infrastructure. Schema export remains additive/reproducible.
E1–E4 and D models, migrations, persistence and production `execute_plan()` remain unchanged.
E5-B owns durable ownership/lifecycle. No runtime exists after E5-A.
