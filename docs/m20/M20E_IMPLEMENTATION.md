# M20-E — Runtime Preparation implementation plan

**Architecture status:** SPECIFIED. **Implementation status:** E1–E2 COMPLETE; E3 IMPLEMENTED (real Core↔Kali acceptance pending); E4–E9 NOT STARTED;
M20-E remains OPEN. M20-D remains CLOSED; M20-F has NOT STARTED. This plan authorizes no
preparation. The architectural
decisions are [ADR 0018](../adr/0018-m20-e-preparation-authority-and-applicability.md),
[ADR 0019](../adr/0019-m20-e-immutable-source-import-and-prepared-resource.md), and
[ADR 0020](../adr/0020-m20-e-trusted-python-preparation-boundary.md). Read
[authority](M20E_RUNTIME_AUTHORITY.md), [source/workspace](M20E_SOURCE_AND_WORKSPACE.md),
[Python runtime](M20E_PYTHON_RUNTIME.md), [recovery/evidence](M20E_PREPARATION_RECOVERY.md),
and [acceptance](M20E_ACCEPTANCE.md) before implementation.

The E goal is exact, evidence-backed preparation of a resource for an already valid plan,
never a finding, safety verdict, or execution grant. The accepted chain is Core
RuntimePreparationAttempt → current D applicability → PreparationPermit → CapabilityRouter
→ ordinary CapabilityRun → `runtime.prepare` → Node provider → CapabilityResult and immutable
manifest/receipt → ordinary Node→Core Artifact sync → Core reconciliation. Separate Core→Node
Artifact Import moves exact retained source before materialization. No extra execution system.

For every slice below, “stop” means **do not advance to the next slice** until its acceptance
and architecture tests pass. Tests use isolated fixtures; E9 is optional/manual real-Kali
validation of E only and never executes a PoC. Slice labels are design gates, not completed
work. Any implementation discovery that changes an ADR requires review before widening scope.

## E1 — Typed preparation contracts and authority boundary (COMPLETE)

- **Goal/authority:** Define immutable, versioned `RuntimePreparationSpec`, `PreparationPermit`,
  `RuntimePreparationReceipt` and manifest schema/binding vocabulary. Intent and digest are
  not credentials. No permit is issued in this slice.
- **Production components/models:** Small shared Contract types only where crossing Core↔Node;
  Core-private attempt/policy types remain Core-owned. Reuse PlanRef, RunRef, ArtifactRef,
  ResourceRef and ExecutionPlanV2. No PreparedRuntimeRef unless proven necessary.
- **Persistence/protocol:** None; schema generation/round trips only. Existing transport and
  runtime behavior unchanged.
- **Tests/manual smoke:** strict serialization, version rejection, immutability, digest
  determinism, wrong-ref and forbidden-authority shapes; no manual smoke.
- **Acceptance/stop:** Types express exact bindings and separate E/F authority without
  turning permit fields into trusted booleans. Stop before DB, dispatch, import or provider.
- **Non-goals:** Policy engine, token signing implementation, source staging, runtime creation.

E1 delivers `RuntimePreparationRef`, `PreparationPermitRef`, `RuntimePreparationManifestRef`
and the shared `PlanDecisionRef` logical identity (the latter was previously Core-private;
Core keeps decision ownership). `RuntimePreparationSpec` pins PlanRef/digest, Mission,
Node/provider, exact source/entrypoint, initial closed Python profile, finite E-only budgets,
network/secret denial, confinement requirements and a closed action set. `PreparationPermit`
adds exact D decision identities/digests, policy context, conditional approval ref, one RunRef,
bounded validity and explicit negative execution authority. This is a typed claim, not an
authenticated permit; trusted issuer admission begins E3.

The immutable `RuntimePreparationManifest`/`RuntimePreparationReceipt` distinguish Node
evidence from Core acceptance. Baseline successful evidence requires empty external dependency
set, complete confinement-feature evidence and bounded observed usage. Pure canonical helpers
separate profile, spec, permit and manifest digests; only generated PreparationRef is excluded
from the request fingerprint. The future `runtime.prepare`/`prepare` input and receipt have
strict versioned JSON Schemas in the Contract v1 bundle; no implementation is registered or
routable. The SDK has a separate typed `RuntimePreparationService` port and side-effect-free
`FakeRuntimePreparationService`; it is **not** yet added to production `ExecutionContext` or
backed by Node, which is E5/E6 work. Unknown versions, extra authority fields and forbidden
profile switches fail validation. No E1 Core/Node migration, repository, protocol, dispatch,
Artifact Import, workspace, Resource, venv, process, secret resolution or source execution
exists. Production `execute_plan()` remains denied.

## E2 — Core durable attempts and preparation admission (COMPLETE)

- **Goal/authority:** Add explicit Core issuance only after current D plan/validation/policy,
  exact approval if required, Mission/source/profile/limits and target admission. DENY and
  unsupported prerequisites are terminal rejection, not assisted fallback.
- **Production components/models:** Core planning/preparation service and repository, current
  applicability projection, permit issuer; reuse Core UoW, Router/Run identities and D records.
- **Persistence/protocol:** Forward Core migration for attempt/permit immutable history,
  request fingerprint, lifecycle/Run/provider/Node identity and receipts. No migration rewrite.
  No protocol change yet.
- **Tests/manual smoke:** migration from prior head, reopen, replay/concurrency, stale D,
  changed scope/profile, DENY, missing/wrong approval, wrong Artifact pin and absent execution
  authorization; no manual smoke.
- **Acceptance/stop:** REQUESTED/REJECTED history and exactly bound permit can be persisted;
  no side effects or dispatch yet. Stop before Node import or capability launch.
- **Non-goals:** Background scheduler, generic policy framework, F authorization.

E2 adds a Core-only `CoreRuntimePreparationAdmissionService`, strict `PreparationRequest`,
durable `RuntimePreparationAttempt` and immutable `PreparationPermit` history. A positive
admission remains `REQUESTED / ELIGIBLE`: its RunRef is **reserved in Core preparation
history only**, with no CapabilityRun row, routing decision, queue or Node invocation.
Unsupported/currently inapplicable requests are durably `REJECTED` with a bounded reason;
terminal rejection is not reopened. Fingerprints pin authoritative plan/D/source/C2/C3
history and selected provider/profile/budgets; a database uniqueness constraint reuses an
identical attempt and permit under concurrency. A changed authority context receives a new
attempt. Permits have an explicit 15-minute issuance window, but are historical claims,
not authenticated Node credentials. `current_admission()` is a separate read-only current
applicability projection; a persisted permit or historical ALLOW is insufficient. D5 current
assessment is checked without creating a D5 assessment, and D6 exact approval is required
only when that current D5 decision requires it. The E baseline rejects missing confinement,
unbounded budgets, external dependencies, target secrets, preparation egress and unsupported
runtime/profile choices. This slice reads retained metadata only; it neither reads source
bytes nor creates a preparation CapabilityRun. E3 owns dispatch and trusted Node admission.

## E3 — Node admission, routing and authorized Core→Node Artifact Import

**Implemented, not yet accepted on the real Core↔Kali link.** Core rechecks current E2
applicability, materializes the already reserved RunRef as a QUEUED CapabilityRun and changes
the attempt from REQUESTED to DISPATCHED in one transaction. It selects the exact advertised
provider through the normal Router. The Node's `runtime.prepare/prepare` advertisement is an
E3 admission-only provider boundary, not an executable source-preparation implementation; no
Capability Runtime `execute()` is called yet. Core and Node retain their separate databases.

The neutral transport revision is **1.5**. E3 requires the separate
`preparation-import-v1` capability advertisement. MCP carries the neutral invocation and
import envelopes; the MCP bearer verifier supplies a request-scoped trusted Core principal.
The permit digest detects mutation/replay conflicts but is not, by itself, authentication.
The Core import-progress migration is `0017_m20_e3_import_progress`; Node authority/import
records and immutable imported-input identities use `0006_preparation_import`.

Only the permit-pinned raw archive and structural manifest are imported. The Node stores
them under `imported-inputs`, separate from produced Artifact spool/outboxes. E3 stops at
verified opaque bytes: no extraction, workspace, Resource, venv, process, secret grant,
target/package/listener network, execution authorization or PoC execution. DISPATCHED is
not preparation completion. E6 owns terminal preparation semantics.

- **Goal/authority:** Allocate the stable preparation RunRef, authorize/import the exact source,
  then route `runtime.prepare` through the existing Router/Run. Enforce the authenticated,
  exact permit on the Node before import/workspace and again at invocation admission. Add a distinct import
  operation with bounded chunks/offsets, resume and hash/size publication.
- **Production components/models:** Narrow neutral transport import envelopes/client/server
  adapters, Core sender, Node admission/import store and registry capability metadata. Node
  never imports Core implementation; Core never imports Node implementation.
- **Persistence/protocol:** Versioned neutral import protocol and forward Node migration for
  admission/import progress. Keep imported bytes separate from produced Artifact spool; no
  Node→Core sync classification for imports. MCP carrier adaptation only; no MCP domain types.
- **Tests/manual smoke:** forged/expired/wrong-Node permit, unsupported protocol, duplicate
  conflicting identity/chunks, offsets, hash/size, partial/restart/reconnect, bounded queue,
  lost ack, paths; no real source manual smoke.
- **Acceptance/stop:** Exact two retained Artifacts become verified Node-local imports only
  under valid permit; invalid requests create no workspace. Stop before extraction or process.
- **Non-goals:** Source parsing, venv, target traffic, F execution.

## E4 — Bounded materialization and workspace/confinement integration

- **Goal/authority:** Reconcile raw ZIP with structural manifest in a private generated
  workspace; publish read-only source only after all structural/hash checks. Begin enforcing
  the ConfinementBackend feature contract without claiming a supported Kali backend yet.
- **Production components/models:** Node materializer, Resource-owned workspace metadata and
  confinement interface/capability probe. No direct Core filesystem access.
- **Persistence/protocol:** Forward Node workspace/resource state migration only if needed;
  retain import and partial-state provenance. No new transport messages unless bounded status
  is essential.
- **Tests/manual smoke:** ZIP traversal, links, devices, collision, file count/size/depth,
  manifest drift, interrupted staging, read-only publication, no source execution; no real
  source manual smoke.
- **Acceptance/stop:** Partial tree never READY; feature-unavailable confinement fails closed.
  Stop before Python environment creation.
- **Non-goals:** Unrestricted extract, source patching, network retrieval, F lease implementation.

## E5 — Trusted Python environment Resource provider

- **Goal/authority:** A provider with closed inspect/create/verify operations creates fresh
  CPython 3.12 venv in a Resource-owned workspace under verified confinement. No arbitrary
  process API becomes preparation authority.
- **Production components/models:** Narrow SDK preparation boundary, Node Python provider,
  Tool Registry interpreter selection, ConfinementBackend implementation and Resource lifecycle.
- **Persistence/protocol:** Node Resource runtime state/config and versioned profile; no Core
  DB change or new transport payload unless manifest schema was insufficient.
- **Tests/manual smoke:** exact interpreter/version, fixed environment, no user site/PATH
  injection, no pip or source import, empty external set, network/socket/filesystem/descendant/
  memory/time/output/storage limits and failure closure. Real Kali backend preflight is planned
  for E9, not assumed from a binary check.
- **Acceptance/stop:** A harmless synthetic source may be staged while only provider-owned
  operations run; Resource not READY until verification. Stop before capability completion.
- **Non-goals:** Dependency installation, package cache, source compilation/execution, secrets.

## E6 — `runtime.prepare` and Core evidence reconciliation

- **Goal/authority:** Complete the normal capability result and immutable manifest/receipt;
  Core verifies binding, waits for Artifact sync and only then marks attempt COMPLETED.
- **Production components/models:** Production `runtime.prepare` capability through SDK,
  Node provider/ArtifactService, existing Result outbox and Core ingestion, Core preparation
  reconciliation service. Core does not import the capability implementation.
- **Persistence/protocol:** Receipt through existing Result envelope; manifest is a normal
  Artifact. Persist accepted manifest identity/digest and ResourceRef in Core; forward migrations
  only if E2 did not reserve these fields. No Artifact bytes inline in Result/Event.
- **Tests/manual smoke:** Result before Artifact → AWAITING_ARTIFACT, corrupt/incorrect manifest,
  wrong permit/Run/Node/resource, duplicate/lost acknowledgements, restart and exact
  acceptance; no real target smoke.
- **Acceptance/stop:** End-to-end synthetic preparation yields accepted immutable evidence and
  ready Resource; `execute_plan()` remains denied. Stop before automated retry or F handoff use.
- **Non-goals:** Vulnerability interpretation, PoC run, target network, execution authorization.

## E7 — Recovery, reuse and cleanup acceptance

- **Goal/authority:** Demonstrate idempotent explicit pumping/reconciliation and conservative
  restart semantics. Historical completion and current availability remain separate.
- **Production components/models:** Core preparation recovery/reuse projection and Node
  import/workspace/Resource cleanup; use existing Run and outbox recovery.
- **Persistence/protocol:** Durable cleanup/quarantine cursor only if needed; no migration
  history rewrite or new authority semantics.
- **Tests/manual smoke:** every [recovery matrix](M20E_PREPARATION_RECOVERY.md) row, lost acks,
  duplicate invocation, changed policy/approval/provider, unavailable Resource, identical
  request reuse and explicit new attempt after safe cleanup; no manual source run.
- **Acceptance/stop:** No duplicate Run, no false READY, no blind rebuild after uncertainty.
  Stop before claiming a vertical acceptance.
- **Non-goals:** Scheduler, generic distributed transaction, mutable venv sharing.

## E8 — Synthetic D→E vertical acceptance

- **Goal/authority:** Prove a valid harmless, supported retained C/B/C/D chain can traverse
  E using normal Router, transport, Node Runtime, Artifact import/sync and Core reconciliation.
- **Production components/models:** Ideally tests only; fix defects in owning layer, not
  test-only bypasses or new product capabilities.
- **Persistence/protocol:** Migration-backed fresh/reopen Core and Node DBs, protocol round
  trips and durable Resource/manifest; no new schema by default.
- **Tests/manual smoke:** full positive chain with verified source, permit, preparation and
  Core COMPLETED; negative D8-like UNSUPPORTED cannot get permit/import/workspace/Resource.
  No real-Kali smoke required here.
- **Acceptance/stop:** Reopen/replay, confinement failures, no source import/entrypoint/target
  traffic, and continued `execute_plan()` denial pass. Stop before E9 real-environment claim.
- **Non-goals:** Real PoC, M20-F, interpreting target effect.

## E9 — Real Kali preparation-only acceptance

- **Goal/authority:** On explicitly configured Kali, prove the backend's required confinement
  properties and the same E chain with a harmless supported fixture, not the retained real
  CERTCC source. Operator controls manual execution.
- **Production components/models:** Manual smoke harness/documentation as needed; no new
  policy exception or fallback for the environment.
- **Persistence/protocol:** Verify real Core/Node reopen, imported exact Artifact identities,
  normal Node→Core manifest sync and current Resource availability. No new migration expected.
- **Tests/manual smoke:** actual Kali feature preflight plus positive preparation-only smoke;
  negative retained CERTCC D8 admission remains zero E records, without rerunning real source.
- **Acceptance/stop:** Evidence proves exact preparation, no package/target network, no source
  execution, Core accepted manifest and restart durability. If confinement unavailable, fail
  closed and do not call E accepted. Stop before M20-F authorization or execution.
- **Non-goals:** Real exploit attempt, vulnerability finding, dependency install, PoC execution.

## Status and historical negative case

The retained CERTCC acquisition `poc-acquisition-2f6a3658a57c42f5ae2252edf1736352`
has authoritative C2@2/C3@2 classification UNSUPPORTED; its D8 PlanningAttempt is
`COMPLETED / UNSUPPORTED / REJECTED_UNSUPPORTED`, with zero ExecutionPlans. It cannot be an E
positive sample. E9 must use a new harmless, supported fixture and valid D chain. Nothing in
this plan changes D history or production behavior. `execute_plan()` remains denied.
