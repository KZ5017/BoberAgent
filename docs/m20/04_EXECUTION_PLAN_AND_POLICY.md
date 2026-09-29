# M20-D — ExecutionPlan and deterministic policy gate

**Status:** D1 typed domain foundation, D2 durable persistence, and D3 authoritative evidence
admission/early C3 rejection implemented. **M20-D remains OPEN**.
[ADR 0016](../adr/0016-immutable-execution-intent-and-policy-authority.md) fixes immutable intent
and separate authority. [ADR 0017](../adr/0017-core-owned-durable-planning-interactions.md)
fixes the future D6 planning Interaction owner.

## Ownership and stop boundary

D is Core-owned, explicitly pumped, deterministic and non-executing. D2 now persists its history:

```text
C3 → PlanningAttempt / PlanProposal → finalized immutable ExecutionPlan
   → PlanValidation → PlanPolicyAssessment → optional OperatorPlanApproval → STOP
```

Even VALID + ALLOW + operator approval is **not execution authorization**. D produces no
preparation/execution permission envelope. E/F separately defines admission and enforcement,
binding exact intent digest, Mission, action, Run, Node/provider, scope and limits.

D stops before Router dispatch, source staging, runtime preparation, dependency installation,
Secret resolution, Resource allocation, Session startup, target contact, ProcessService and
execute_plan(). The production Node denial remains unchanged.

## Typed shared intent

ExecutionPlan schema v2 evolves the existing Contract concept; the legacy ExecutionPlan class
remains decodable (including unversioned M1 JSON). Legacy ExecutionPlanStatus is presentation
only, never authoritative validity or permission. Deserializing legacy data cannot qualify it
for the future executor. V2 has no mutable status or enforcement-critical metadata bags.

Frozen nested records/tuples pin plan/Mission/acquisition identity, raw Artifact ref/hash/size,
manifest ref/hash and commit; target; source-relative entrypoint/hash/evidence; runtime/version/
platform/location; bindings; ordered invocation; environment allowlist; typed dependencies;
Secret/Credential references and purpose; Resource/Session requirements; filesystem/network
constraints; finite wall/process/memory/output/write budgets; expected evidence/results.

Targets distinguish HOST, IP, URL, SERVICE_ENDPOINT, FILE, DIRECTORY, REPOSITORY and UNKNOWN.
Only matching typed target-role bindings are representable. File/directory/repository inputs
cannot deserialize as network endpoints; DIRECTORY cannot bind an Asset network address;
UNKNOWN cannot silently map by parameter name. Selection/mapping validation is later D work.

Bindings separate parameter identity, source, type, channel, requiredness, resolution and
provenance. Sources cover Mission target, literal, operator answer, SecretRef, CredentialRef,
callback requirement, artifact/source path and managed runtime path. Sensitive bindings contain
refs only, never values, secret hashes or transport grants. Scalar literal/operator values are
ordinary non-secret parameters: the schema cannot detect a secret disguised as ordinary text;
later admission must maintain that invariant. Concrete Node-local paths and live handles are absent.

Resource/Session requirement descriptors are distinct from optional explicit allocated refs.
An unallocated requirement is not an invalid explicit ref. No D1 lookup or allocation occurs.
Filesystem scope BOUNDED/UNKNOWN/BROAD is explicit; UNKNOWN is never silently bounded. Source
is read-only; managed writable roots, allowed operations, relative paths/patterns and cleanup
are declared. Network classes separately represent target/callback/listener/public/preparation/
multi-target/unknown; unspecified destinations are DISALLOW. Schema validity is not confinement.

## Invocation evidence and C3 transition

Current authoritative inspection profiles are C2@2 and C3@2; historical @1 is immutable.
C2@2 lacks sufficient option, arity and positional interface evidence for unrestricted automatic
argv derivation. D-v1 may accept an explicit reviewed typed InvocationLayout, carrying operator
review/evidence identity, never an OBSERVED source fact. No new source parsing belongs in D.

- AUTOMATIC permits planning to begin, not execution.
- ASSISTED permits partial proposals with explicit unresolved bounded requirements.
- UNSUPPORTED retains the exact C3 document/reasons/blocker refs, yields planning disposition
  UNSUPPORTED and no finalized plan. D cannot silently clear C3 blockers.

## Core records and decisions

PlanningAttemptRef, lifecycle, request, proposal/revision history and answer provenance remain
Core-private. Lifecycle: REQUESTED, EVALUATING, WAITING_INPUT, COMPLETED, FAILED, INTERRUPTED,
CANCELLED. Disposition: VALID, REQUIRES_INPUT, UNSUPPORTED, INVALID. Do not use Run lifecycle.

PlanValidation, PlanPolicyAssessment and OperatorPlanApproval are distinct types. Decisions
bind exact plan ref/digest, Mission and scope; validation binds its rule profile/version;
policy/approval bind policy profile/version. Policy decisions are NOT_EVALUATED, ALLOW, DENY,
REQUIRES_APPROVAL. Operator approval records deliberate APPROVE/REJECT, never a Node credential.
PlanningAnswer records future D6 revision provenance; D1 changes no M15 behavior.

The initial positive policy-profile schema is single Mission network target, attacker-side
Python on Linux/Kali, user-space/noninteractive, source available, explicit endpoint/network,
finite limits, no broad/destructive/critical-unknown effects. It is a definition, not an
evaluator, generic policy language or execution authority.

## Canonical identity

Planning request fingerprint identifies exact source/inspection/target/proposed choices and
planning profile and requested policy identity. Intent digest excludes generated PlanRef/creation time while retaining all
semantic intent. Decision-context fingerprint identifies intent/scope/inspection digest and
validation/policy configuration and optional reference/status-only prerequisite snapshot digest. They are not interchangeable and are not signatures.

Map keys are canonical; declared set-valued collections are sorted/deduplicated; ordered argv
tokens preserve order. Generated IDs/timestamps are excluded only where nonsemantic; exact
source and inspection refs remain pinned. No connection, concrete local runtime path, resolved
Secret or secret-value hash belongs in these inputs. Changing argv order changes intent digest.

## Slices and acceptance

D1 supplies strict schemas, pure canonical helpers, tests and documentation only: no tables,
migrations, repositories/services, construction pump, authoritative validator/policy evaluation,
HITL request generation or dispatch. D2 implements persistence primitives; D3 adds metadata-only authoritative admission, not a planner.
Later D slices construct and evaluate
against authoritative Mission/scope/evidence/prerequisite state. D6 implements ADR 0017 owners.
The exact remaining slice implementation is not authorized by D1.

Later D validates Mission/source/target/evidence consistency, entrypoint and exact source,
current scope, supported runtime/bindings/requirements and finite effects/limits. It records
separate decisions and reasons, preserves rejected evidence and fails closed without repairing
model mistakes. Approval cannot override DENY. Changed source/scope/policy needs fresh decisions.

D completion requires durable replay-safe intent/decision history and no execution side effects.
D1 tests strict v2/legacy serialization, nested immutability, order-sensitive digest, canonical
sets/maps, refs-only sensitive requirements, target distinctions, separate decisions, C3 blocker
retention and narrow policy shape. Node forged-plan refusal, permission admission, staging and
locally enforceable isolation acceptance belong to E/F, not D.

## Implemented D2 persistence boundary

[Implementation details](M20D_IMPLEMENTATION.md#d2--durable-history-and-atomic-reuse) describe
Core migration `0013_m20_d2_planning`, three principal tables and existing-UoW repositories.
Requests and strict proposal history are versioned; finalized V2 intent and separate decisions
are immutable. Finalization atomically inserts supplied intent and marks VALID/COMPLETED,
without assessing source truth or granting authority.

A partial unique request-fingerprint index atomically reuses active/completed determinations.
Failed/interrupted/cancelled attempts remain history; a deliberate new request may create a new
identity. Proposal changes require expected revision/state and preserve the original request.
UNSUPPORTED/INVALID completion has no plan; WAITING_INPUT retains unresolved descriptors without
creating M15 Interactions. Explicit cutoff recovery interrupts only unproven EVALUATING rows.

The exact C3 document digest is distinct from its C2-parent semantic digest. Stored intent and
decision-context fingerprints are verified with D1 helpers; unknown/corrupt documents fail closed.
Changed scope, policy or reference/status prerequisite context needs new decision records.
History lookup is not current applicability or approval. No automatic planner/validator/policy
engine, HITL prompts, dispatch, permission envelope, staging or runtime work exists in D2.

## Implemented D3 evidence admission

`CorePlanningAdmissionService.admit(PlanningAdmissionRequest)` accepts only Mission/acquisition,
C2/C3 refs and planner/requested-policy identities. It derives hypothesis/candidate ownership
from Core; caller documents, hashes, classifications, blockers and proposals are forbidden.
The service loads persisted Mission, acquisition, C2/C3, hypothesis/candidate, Asset/optional
Service, producing Run and Artifact catalog metadata. Acquisition/C2/C3 must be COMPLETED,
with exactly `m20-c2-deterministic@2` / `m20-c3-support-classifier@2`. Historical @1 stays
readable but inadmissible; unknown versions and inconsistent configuration fail closed.

Source refs/hashes/size/commit, Mission and upstream relationships must match. Catalog descriptors
and AVAILABLE metadata must agree with the completed acquisition receipt. D3 recomputes existing
configuration identities and the C2 semantic-document digest, verifies both persisted C3 parent
ref/digest locations, strictly decodes C3 and checks bounded item/conflict/coverage references.
The separately pinned C3 classification-document digest uses D1 canonicalization; it is not
the C2-parent `semantic_document_sha256`. Immutable inspection/acquisition refs retain their
configuration and source-identity provenance; no Node/runtime/transport fields enter identity.
No ZIP/manifest/source/citation reader, rehash, extraction or reclassification runs in admission.

Admission is distinct from disposition/validation/policy:

- AUTOMATIC → ELIGIBLE_AUTOMATIC, REQUESTED, no disposition or proposal.
- ASSISTED → ELIGIBLE_ASSISTED, REQUESTED, exact assistance provenance, no Interaction/wait/proposal.
- UNSUPPORTED → REJECTED_UNSUPPORTED, atomic REQUESTED→EVALUATING→COMPLETED/UNSUPPORTED,
  entire original C3 document including assistance reasons retained, no plan or decisions.

Invalid/undecodable/incompatible provenance raises a bounded admission error **before** attempt
creation, rather than forging an UNSUPPORTED classification or partial request identity.
Unexpected failure rolls back the complete UoW. D2 conflict-safe insertion/index owns reuse;
replayed existing active/completed attempts are returned unchanged, not resumed or retried.
`get_admission()` inspects stored admission, not current permission. No new migration or Contract
change is needed. PlanningRequest permits `proposal=None` at this preconstruction boundary;
existing proposal-bearing requests and fingerprints remain unchanged.

M20-D remains OPEN. D4 construction, D5 evaluation and D6 HITL remain deferred; production
execute_plan() stays denied. Admission is neither safety nor authorization.
