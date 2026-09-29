# M20-D — Implemented slices

D1 and D2 are implemented; **M20-D remains OPEN**. D1 supplies typed domain intent;
D2 supplies persistence primitives only. Neither performs planning construction, authoritative
validation, policy evaluation, HITL behavior or dispatch.

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
InitialPlanPolicyProfile and DecisionContext. There is no planning application service.
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
D3–D6 construction/validation/policy/interaction work and all E/F preparation/execution remain
unimplemented. Production execute_plan() stays denied.
