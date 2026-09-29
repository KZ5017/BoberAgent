# ADR 0016: Immutable execution intent and separate policy authority

**Status:** Accepted for M20-D1. No execution path is enabled.

## Decision

Core constructs a deeply immutable ExecutionPlan schema v2. Shared execution semantics live
in Contracts; planning history, inspection provenance, validation, policy and approval records
remain Core-owned. ExecutionPlan is intent, not authorization.

The boundary is C3 → PlanningAttempt / PlanProposal → immutable plan → PlanValidation →
PlanPolicyAssessment → optional OperatorPlanApproval → STOP. These are separate records.
Even VALID + ALLOW + approved is not preparation/execution authorization or a Node credential.
E/F must separately define and enforce a permission envelope bound to exact intent digest,
Mission, action, Run, Node/provider, scope and limits before staging or launch.

Legacy plans remain decodable. Their ExecutionPlanStatus is legacy/derived presentation, never
executor authority. V2 has no mutable status and no hidden enforcement fields in JSON metadata.
Frozen records and tuples encode target, runtime, bindings, ordered argv, dependencies,
Secret/Credential refs, Resource/Session requirements, filesystem/network constraints and budgets.
Unknown effect scope is not bounded; unspecified network destinations are disallowed in future
enforcement. Local runtime paths, live objects and resolved secret/grant material are absent.

Request fingerprints, intent digests and decision-context fingerprints are distinct. Map keys
and set-valued collections canonicalize; argv order is preserved. Generated IDs/timestamps are
excluded where nonsemantic. Secret values and their hashes never enter fingerprints. Digests
identify semantic data, not authority.

C2@2 lacks sufficient CLI interface evidence for unrestricted automatic argv derivation.
Reviewed typed InvocationLayout may be provenance-bearing operator input, never OBSERVED fact.
D adds no parser. C3 AUTOMATIC permits planning to begin; ASSISTED permits partial proposals;
UNSUPPORTED preserves exact blockers and yields no finalized plan.

## Rejected alternatives

- Mutable plan status as authority or caller-controlled APPROVED permits post-decision changes.
- CapabilityRun lifecycle as planning lifecycle conflates evaluation and execution.
- Node-owned planning moves assessment/policy ownership outside Core.
- Metadata-based hidden enforcement fields cannot provide strict shared semantics.
- Approval as a launch token cannot prove current scope or Node confinement.

## Implementation boundary

D1 supplies schemas and pure fingerprints only. D2 owns persistence; later D slices own
construction, validation and policy evaluation; D6 owns planning interactions. D stops before
dispatch, staging, preparation, installation, Secret resolution, Resource/Session allocation,
target contact, ProcessService or execute_plan(). Production execute_plan() stays denied.
E/F admission and confinement require separate reviewed work; a venv is not hostile-code isolation.
