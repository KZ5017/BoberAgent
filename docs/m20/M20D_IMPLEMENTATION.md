# M20-D — Implemented slices

D1 through D6 are implemented; **M20-D remains OPEN**. D1 supplies typed domain intent;
D2 supplies persistence primitives; D3 admits authoritative persisted evidence and durably rejects
C3 UNSUPPORTED. D4 adds narrow Python construction and deterministic validation. D5 adds
deterministic policy assessment. D6 adds separate Core-owned planning assistance and operator
policy approval; no slice dispatches, stages, prepares or executes.

## Contract API

```python
from boberagent_contracts import (
    ExecutionPlan, ExecutionPlanV2, decode_execution_plan, execution_intent_digest,
)
```

ExecutionPlan is legacy v1, with an explicit default version marker for old unversioned data.
ExecutionPlanV2 is the current deeply frozen intent. decode_execution_plan accepts either and
rejects unknown versions; decoding does not upgrade legacy data or confer executor eligibility.
The Contract major version remains v1, independent of the plan document schema version.
SDK execute_plan and the production Node's denial are unchanged.

Typed components live in public modules plan_values and plan_requirements. They cover source
pins, network/source targets, entrypoint/runtime, reference/scalar/path/callback bindings,
operator-reviewed ordered invocation, explicit environment, dependency classes, sensitive
requirements, distinct Resource/Session requirements, filesystem/network limits and expected
evidence/results. No nested mutable dict/list bags exist in finalized v2. Pydantic frozen
models prevent ordinary mutation; deliberate bypass APIs such as model_construct/model_copy
are not trusted admission and later layers must revalidate serialized intent.

Source-relative paths are lexically checked, not opened/resolved. Network and filesystem
constraints describe intent, not a sandbox. UNKNOWN remains unknown. Scalar parameters are
non-secret by convention; no schema can recognize every secret disguised as ordinary text.
Sensitive roles require SecretRef/CredentialRef and explicit purpose, not plaintext or grants.

## Core API

boberagent_core.planning exposes PlanningAttemptRef/lifecycle, PlanningRequest, partial
PlanProposal and revisions, inspection pins, PlanningAnswer provenance, disposition,
PlanValidation/reasons, PlanPolicyAssessment, OperatorPlanApproval, the narrow
InitialPlanPolicyProfile and DecisionContext. D3 provides narrow evidence admission and D4 provides explicit construction/validation services,
described below.
D2 repository access uses the existing Core unit of work, described below.
The exact C3@2 document/blocker refs remain attached to the request; UNSUPPORTED cannot produce
a finalized plan. Historical C2/C3@1 models remain readable, but new D-v1 inputs require @2.

Validation, policy and approval are different types tied to exact intent/Mission/scope.
None contains an authorization token, executable Run, Node identity or permission envelope.
Later E/F must provide a separately reviewed admission/enforcement mechanism.

## Pure identity helpers

- planning_request_fingerprint pins source, current inspection and proposed choices/profile.
- execution_intent_digest excludes generated PlanRef and creation time, retaining semantic intent.
- decision_context_fingerprint pins intent/scope/inspection digests and policy/validation versions.

Map keys canonicalize. Tuple fields marked collection_semantics=set sort/deduplicate only for
digests, not by rewriting the model. Invocation.arguments remains ordered. Identical ref-based
sensitive requirements have no secret-value hashes. Digests are identifiers, not signatures.

Regenerate the authoritative schema with:

```shell
uv run boberagent-contract-schema packages/contracts/schemas/contract-v1.schema.json
```

## Boundaries and follow-up

ADRs 0016/0017 define intent authority and deferred D6 PlanningAttempt-owned interactions.
C2@2 has no complete CLI grammar; reviewed InvocationLayout is operator input, never OBSERVED.
D2 implements forward persistence; subsequent D slices own construction, authoritative validation,
policy evaluation and D6 interaction behavior. No E/F staging, runtime, installation,
Secret resolution, allocation, target contact, process execution or authorization is added.

## D2 — Durable history and atomic reuse

Migration `0013_m20_d2_planning` follows `0012_m20_c1_inspection`, without modifying
historical migrations or C2/C3 documents. It adds three Core-owned tables:

| Table | Persisted truth |
| --- | --- |
| planning_attempts | Logical attempt/Mission/upstream refs; C2 parent digest and distinct exact C3 document digest; planner/requested-policy identities; canonical request fingerprint; versioned original request and complete proposal-revision history; current revision, lifecycle/disposition, code-only diagnostics and aware timestamps |
| execution_plans | One strict immutable V2 per attempt; PlanRef/Mission, schema, verified intent digest, JSON, optional superseded PlanRef and creation time |
| plan_decisions | Append-only discriminated validation/policy/operator records; stable DecisionRef, PlanRef/digest, evaluator profile/version, exact context/fingerprint and timestamps |

Raw/manifest refs, hashes, source size/commit, C2/C3 profiles and exact C3 blocker references
remain pinned in the typed original request. No C2 source document is copied. C3
`semantic_document_sha256` is its **C2 parent** digest. The separately named
`classification_sha256` is verified against the exact C3 document with D1 canonicalization.

### Repository surface

```python
with database.unit_of_work() as work:
    attempt = work.planning_attempts.add(requested_attempt)
    stored = work.planning_attempts.get(attempt.planning_attempt_ref)
    # Explicit persistence of already-supplied intent; no evaluator runs here:
    plan_record = work.planning_attempts.finalize(
        attempt.planning_attempt_ref, supplied_v2,
        intent_sha256=execution_intent_digest(supplied_v2),
        expected_state=attempt.lifecycle, expected_revision=len(attempt.revisions),
        completed_at=now,
    )
```

The UoW also exposes `execution_plans` (add_finalized/get/get_by_attempt/get_by_intent_digest)
and `plan_decisions` (append/get/list_for_plan/find_by_context). None commits independently.
Use `planning_attempts.finalize` to atomically couple plan insertion and attempt completion;
low-level `add_finalized` alone does not imply completion, validation or policy authority.

Request identity includes the requested policy profile/version. A SQLite partial unique index
permits at most one equivalent REQUESTED/EVALUATING/WAITING_INPUT/COMPLETED determination.
Creation uses conflict-safe insertion and returns that existing determination, including across
independent concurrent UoWs. FAILED/INTERRUPTED/CANCELLED release the reusable slot but remain
immutable history: a deliberate new request with a new AttemptRef may create another attempt.
There is no implicit retry, generation scheduler or process-local deduplication lock.

Lifecycle writes require expected state and revision; terminal rows cannot reopen or be
rewritten. WAITING_INPUT requires REQUIRES_INPUT. Non-plan completion is UNSUPPORTED or INVALID.
VALID is possible only via explicit intent finalization. C3 UNSUPPORTED cannot acquire a plan or
lose its exact blockers. Terminal records have completion times. Diagnostic details are bounded
code/reference data, not free-form exception/source text.

Proposal updates append contiguous revisions to versioned JSON with the exact prior revision
digest, source pins, answer provenance and monotonic timestamps. Stale expected revisions/states
fail. The original request/fingerprint is immutable; draft changes never rewrite request identity.
Answers may carry future D6 InteractionRefs, but no Interaction is created or routed by D2.
Finalization checks the active/current revision and rolls back plan insertion on conflict,
even if the caller catches the error and commits other work. SQLite savepoints explicitly begin
an outer database transaction when needed to preserve Core UoW rollback under legacy driver mode.

### Decisions, recovery and limits

Decisions bind the exact plan digest, Mission, scope, evaluation profile and C3 context.
A prerequisite-state digest may pin **reference/status metadata only**, never resolved sensitive
values or their hashes. Scope, policy settings or prerequisite changes alter the context
fingerprint. Context lookup returns history, not a current applicability/approval determination.
A new decision gets a new DecisionRef; identical replay of that ref is idempotent, conflicting
reuse is rejected. SQL guards also forbid plan/decision updates/deletes and terminal attempt
rewrites. VALID + ALLOW + operator APPROVE creates no Run, grant, permission or authorization.

Opening Core does not recover or run planning. Explicit
`recover_unproven_active_attempts(cutoff=..., recovered_at=...)` interrupts only EVALUATING
rows at/before the cutoff. REQUESTED, WAITING_INPUT and completed determinations remain unchanged.
No new attempt, plan or interaction is created during recovery.

Strict loading verifies version markers, typed documents, row/document identities, revision
chains and canonical digests. Corrupt/unknown versions fail closed through safe
PlanningPersistenceError/PlanningConflict without rendering raw documents or SQL parameters.
Legacy plans remain decodable elsewhere but cannot enter V2 finalized persistence automatically.
Arguments preserve order across storage; declared semantic sets canonicalize only for digests.

Sensitive bindings/requirements persist SecretRef/CredentialRef, roles and purpose only.
D2 neither reads secret values nor issues grants. As in D1, a schema cannot identify every secret
disguised as an ordinary scalar/label; later admission must retain the non-secret parameter rule.
Digests are identifiers, not signatures against a privileged database editor.

Verification covers migration from empty/prior-head databases, preserved upstream data,
constraints, restart/recovery, concurrent reuse, CAS, immutable decisions, rollback, strict V2,
ordered arguments, negative determinations and sensitive-reference regression cases.
At the D2 boundary, construction/validation remain separate application responsibilities.
At D2 closure, D5/D6 policy/interaction work was not yet implemented. It is now described in
[D5](M20D5_POLICY.md) and [D6](M20D6_PLANNING_HITL.md). E/F remain unimplemented; production execute_plan() stays denied.

## D3 — Authoritative evidence admission and early C3 rejection

```python
from boberagent_core.planning import PlanningAdmissionRequest
from boberagent_core.planning.admission import CorePlanningAdmissionService

service = CorePlanningAdmissionService(database)
result = service.admit(PlanningAdmissionRequest(
    mission_ref=mission_ref, acquisition_ref=acquisition_ref,
    semantic_inspection_ref=c2_ref, classification_inspection_ref=c3_ref,
    planner_profile="m20-d-planning", planner_version="1",
    policy_profile="m20-python-single-target", policy_version="1",
))
stored = service.get_admission(result.attempt.planning_attempt_ref)
```

This is an immediate deterministic pump, not a planner or background scheduler. Caller input is
refs/profile identities only; strict decoding (including model_copy bypass checks) rejects added
truth/proposal fields. All source hashes, ownership and classification come from Core repositories.
Hypothesis/candidate refs derive from acquisition. Mission ownership traverses hypothesis, candidate,
Asset, optional Service and the acquisition-producing Run. Equal hashes never replace ownership.

All three upstream stages must be COMPLETED. Only C2@2/C3@2 are admitted. C2 pins must equal
acquisition raw/manifest refs, hashes, raw size and commit; C3 must bind the same source and exact
C2 ref/digest in both document and typed configuration. Existing configuration hash calculations
are shared pure helpers, byte-for-byte unchanged. Current C2/C3 typed documents and referenced
semantic items, unknowns, conflicts and coverage are validated from metadata only. Artifact catalog
AVAILABLE state/descriptors must agree with receipt; no file is opened or rehashed, so admission
is not a fresh physical-byte integrity assertion. Future integrity rechecks remain separate.

D2 request identity includes Mission/upstream refs, source pins, C2 ref/profile/semantic digest,
C3 ref/profile/exact classification-document digest and planner/requested-policy identity.
C3 semantic_document_sha256 remains the **parent C2 digest**. C3 classification_sha256 uses
D1 canonical_digest. Source/configuration identities remain traceable through immutable acquisition/
inspection refs rather than duplicating entire C2/configuration documents. Generated attempt ID/time
and runtime/transport/Node identity do not affect reuse. Changed admitted evidence or policy identity
creates a different fingerprint; unknown profile versions cannot become new accepted determinations.

AUTOMATIC and ASSISTED yield ELIGIBLE_AUTOMATIC/ELIGIBLE_ASSISTED with REQUESTED attempts, no
VALID/ALLOW/approval implication. Exact assistance refs remain in C3; no WAITING_INPUT or Interaction
is generated. UNSUPPORTED yields REJECTED_UNSUPPORTED with COMPLETED/UNSUPPORTED. The entire strict
C3 document preserves reason codes, item/conflict/coverage references, material unknowns **and**
assistance reasons; no source text or exception payload is copied into diagnostics. All paths have
proposal=None, zero revisions, no finalized plan and no plan decisions. PlanningRequest makes only
the existing proposal field optional; old proposal-bearing JSON and canonical fingerprints do not
change. No schema migration, dependency or shared Contract change is introduced.

Invalid provenance fails before insertion with AdmissionErrorCode/PlanningAdmissionError; it never
pretends the PoC itself was classified UNSUPPORTED. This deliberately avoids manufacturing an
incomplete canonical request for COMPLETED/INVALID. New unsupported insertion and lifecycle writes
share one UoW; internal failure rolls everything back, even after lifecycle writes. Existing D2
atomic conflict-safe reuse handles independent concurrent calls/restart. Stored active/completed
attempts are returned unchanged, not implicitly advanced or retried. Failed/interrupted/cancelled
history follows D2 explicit new-request semantics; no automatic scheduling is added.

Tests build real persisted synthetic acquisition/C2/C3 chains through existing services, then forbid
Artifact/citation/inspection/classifier calls during admission. They cover all classifications,
current/historical/unknown profiles, ownership/source/configuration/parent mismatches, strict stored
corruption, caller tampering, separate digests, changed evidence/policy identity, rollback, concurrent
independent UoWs and reopen/reuse. Every admission path verifies no plan/decision/Interaction rows.
A synthetic negative covers the retained real case’s coverage/material-unknown/target-boundary reason
categories; the real CERTCC source is not accessed or run. Dedicated architecture guards forbid
construction, readers, Router, transport, execution, secrets, allocation, Reasoner and Knowledge.

**M20-D remains OPEN.** At D3 closure D5/D6 were pending; they are now implemented separately.
E/F remain unimplemented and production execute_plan() remains denied.

## D4 — Narrow Python construction and deterministic validation

`CoreExecutionPlanningService.construct(PlanConstructionRequest)` is an explicit Core pump;
`get(PlanningAttemptRef)` inspects stored history. Public typed inputs/results are exported
from `boberagent_core.planning`; the service lives in `.planning.construction`.
The request contains the admitted AttemptRef, expected proposal revision, explicit typed
network target, reviewed InvocationLayout, bindings, runtime declaration and finite limits.
It cannot supply source truth, classification, a plan, policy decision or execution authority.

D4 resolves D3's exact authoritative request again in the same UoW, without admitting a new
attempt or reopening Artifacts. Completed acquisition/C2@2/C3@2, configuration and ownership
checks are unchanged. Invalid upstream evidence aborts without writing construction history.
Only AUTOMATIC can finalize. ASSISTED is conservatively non-final or invalid under the narrow
slice; UNSUPPORTED cannot enter construction and its exact historical reasons remain intact.

### Reviewed invocation, target and bindings

The existing D1 `InvocationLayout` is the reviewed-input model: `OPERATOR_REVIEWED` origin,
explicit review_id, exact selected C2 parameter IDs in evidence_ids, and ordered typed tokens.
It is operator/reviewer planning input, **not OBSERVED source evidence**. Layout and binding
provenance are preserved in proposal revisions and finalized intent. No README, parameter-name
convention, source parser or model derives missing argv structure.

Exactly one CODE/OBSERVED Python SCRIPT_MAIN_GUARD candidate is eligible. Intent pins its
relative path, coverage/citation entry hash, language, SCRIPT form and item ID, with matching
Python-source/main-guard facts. Multiple eligible entrypoints require later input; none is
guessed. No Artifact bytes are read or freshly rehashed by planning.

The initial positive target is one explicit TCP SERVICE_ENDPOINT: Mission-owned AssetRef,
exact persisted primary address, port, transport and optional owned ServiceRef. HOST/IP
parameter roles can bind that typed endpoint; actual rendering belongs to future execution.
File/directory/repository/unknown/URL targets are outside this first positive slice. Service
identity, Asset ownership, port and transport must match. Bootstrap scope follows the existing
Mission-owned-Asset rule, with a digest of Mission/Asset/address metadata; no new scope policy,
DNS lookup, address expansion or target contact is introduced.

Every selected entrypoint parameter needs an explicit resolved argument-channel binding,
including optional/defaulted parameters. This intentionally narrower v1 does **not** omit or
recover defaults. Missing/redacted values yield INVALID without recovering source plaintext.
Supported sources are MISSION_TARGET for TARGET_HOST and LITERAL/OPERATOR_VALUE integer
TARGET_PORT/TIMEOUT, preserving candidate ref, requiredness, type, channel, resolution and
Mission/reviewer provenance. Port equals the selected endpoint; timeout is positive and
within the declared wall budget. Other roles/sources remain outside this slice.

Reviewed option-value (separate/equals), positional, and option-followed-by-binding structures
are supported. Each binding must be delivered exactly once. Standalone flags, unknown/repeated
bindings, mismatched channels and arbitrary text are rejected. No shell string or quoting engine
exists. The ordered Contract layout remains authoritative; changing token order changes digest.

### Runtime, effects and validator

Runtime intent is Python `>=3.12,<4`, attacker-side Linux/Kali, user-space and noninteractive.
No executable lookup/version probe/venv occurs. Only CODE/OBSERVED STDLIB_LOOKING imports enter
the positive dependency slice; this records C2's apparent dependency evidence, **not proof of
installed modules**. Unknown, third-party, build, local or other dependencies are not installed
or promoted to stdlib. Rejected proposal requirements remain explicit.

The first slice permits no source filesystem mutation, environment requirement, sensitive
binding, Resource/Session requirement, listener/browser, subprocess or unknown destination.
Filesystem intent is bounded/read-only with no writable rules. Network intent is one selected
TCP endpoint only; unspecified destinations are DISALLOW. Public/preparation/callback/listener/
multi-target/unknown destinations are rejected. Only network-connect indicators are accepted;
C2 material unknowns, conflicts, risks and requirements cannot be cleared by a reviewer.
These are consistency/support checks over C2 evidence, **not a proof of arbitrary-source safety
or a runtime sandbox**. E/F must implement enforceable confinement independently.

All ExecutionLimits fields must be explicit: bounded wall, memory, output, process and write
budgets; initial process_count=1 and disk_write_bytes=0. Stdout/stderr are the expected evidence.
Limits describe intent; D4 enforces nothing on a running system.

Pure validator `m20-d4-plan-validator@1` uses fixed first-failure precedence: schema, Mission/
scope, source, C2/C3 provenance, admission, entrypoint, reviewed layout, binding completeness/
types/target role/single target, runtime, dependencies, filesystem, network, finite limits,
noninteractive/user-space/attacker-side and unresolved semantics. Reasons are bounded codes
and evidence refs, never source excerpts or exception details. Complete V2 candidates also
cross model validation; C3 AUTOMATIC alone does not create a plan or VALID decision.

### Durable outcomes, replay and atomicity

- VALID: one immutable V2 + one separate PlanValidation + COMPLETED/VALID attempt, atomically.
- INVALID: COMPLETED/INVALID, rejected proposal revision and bounded diagnostic codes; no plan
  or plan decision. References are retained in that proposal and authoritative request.
- REQUIRES_INPUT: WAITING_INPUT/REQUIRES_INPUT with a partial proposal and explicit unresolved
  requirement code for missing reviewed layout or bounded entrypoint choice. No D6 Interaction
  is created. Critical unknown effects are never an operator-clearable wait.

A proposal update appends D2's next contiguous revision and exact prior-revision digest.
Changed active input requires the current expected revision; stale input conflicts. Identical
waiting/completed construction replays return stored history unchanged (generated unresolved
markers are not new caller input). Changed finalized input conflicts, never rewrites intent.
There is no automatic retry/resume scheduler.

D2 finalize and decision append share the existing outer UoW. An append/internal failure after
finalization rolls back the entire revision/plan/completion transition; no VALID attempt without
validation or orphan plan is committed by D4. No repository or migration redesign is needed.
Concurrent independent callers yield one plan and one validation history, with stale callers
conflicting or observing the identical completed result.

Validation binds PlanRef, semantic intent digest, validator/version, Mission, current scope
digest and exact C3 classification digest in the existing decision context. The context contains
the supported requested profile declaration, not an evaluated policy. D4 v1 accepts the current
`m20-python-single-target@1` profile identity only. Returned policy is NOT_EVALUATED and runtime
readiness NOT_ASSESSED; no policy assessment, approval, permission, Run, Node token, grant or
dispatch record is created. History inspection/replay is not a fresh execution permission.

Tests use harmless retained synthetic Python evidence through real acquisition/C2/C3/D3 services.
They prove positive construction/validation, negative and assisted boundaries, independent pure
validator defenses, exact hashes/refs, argument/digest sensitivity, explicit operator values,
reopen/reuse, CAS, rollback after finalization, concurrent independent UoWs and no byte/runtime
access. Generated PlanRef/time do not change semantic digest; target, bindings, limits and argument
order do. Existing migration-backed tests verify prior/fresh database compatibility; D4 adds no
migration, dependency or shared Contract change.

That is the historical D4 stop boundary. [D5 implementation](M20D5_POLICY.md) now adds a
registered narrow profile, pure checker, strict validation prerequisite and append-only policy
assessment with migration `0014_m20_d5_policy_identity`. [D6](M20D6_PLANNING_HITL.md) now
adds HITL and exact operator approval. **M20-D remains OPEN.** E/F staging, preparation and
execution remain deferred; production execute_plan() remains denied.
