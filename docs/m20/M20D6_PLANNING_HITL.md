# M20-D6 — Core planning assistance and operator policy approval

D6 is implemented as Core-owned, durable, explicitly pumped interaction. M20-D later
closed after D7/D8 acceptance. D6 does not dispatch, stage, prepare or
execute a PoC; readiness remains `NOT_ASSESSED`, authorization remains `NONE`, and
production `execute_plan()` remains denied.

## Two lifecycles, two authorities

Pre-finalization assistance belongs to a `PlanningAttempt` in `WAITING_INPUT / REQUIRES_INPUT`.
D4 writes the proposal revision, WAITING_INPUT transition and a bounded Core planning
Interaction in one transaction. The question pins the AttemptRef, MissionRef, proposal
revision, purpose and stable candidate/parameter IDs. The response must match those
identities and the offered type/options. An accepted response appends a new proposal
revision with `PlanningAnswer` provenance; an explicit `resume()` pump re-runs D4.
There is no in-memory continuation. Identical answer replay is idempotent, conflicting
or stale answers fail, and restart retains the pending question and attempt state.

Supported assistance is deliberately narrow: select one C2-observed Python entrypoint
from offered IDs, supply a bounded non-secret integer for a TARGET_PORT or TIMEOUT
binding, or provide a reviewed `InvocationLayout` pinned to the selected entrypoint's
parameter candidates. The narrow C2 `PARTIAL / EXTRACTOR_LIMITATIONS` coverage caused
*only* by multiple entrypoint candidates may be resolved by an exact persisted choice;
other unknowns, C3 blockers, unsupported runtime/dependencies, broad/destructive
effects and out-of-scope targets remain blocked. Runtime/dependency review purpose
codes exist, but have no permissive D6 answer path in this slice. Operator input is
not rewritten as C2/C3 evidence and cannot carry secret plaintext.

Post-finalization policy approval is a **different** Core Interaction with purpose
`POLICY_APPROVAL` and choices `APPROVE` / `DENY`. It can be requested only for a current
D5 `REQUIRES_APPROVAL` assessment of a completed, VALID PlanningAttempt and immutable
ExecutionPlanV2 with matching VALID PlanValidation. The pending Interaction belongs to
the PlanningAttempt but **does not reopen it**: it remains `COMPLETED / VALID` across
restart and after response. A response appends a separate immutable
`OperatorPlanApproval` decision (APPROVE or historical REJECT); it never mutates the
plan, validation or policy assessment.

Approval applicability lookup re-evaluates current D5 context and matches the exact
plan/intent, validation decision, Mission/scope, policy profile/version/digest,
assessment identity and context fingerprint. Changed context makes old approval
historical only. `ALLOW` needs no synthetic approval; hard `DENY` cannot be overridden.
Approval is **not** execution authorization, a permission envelope, Run, grant or
runtime-readiness assessment.

The existing M15 CapabilityRun-owned interactions remain separate. D6 uses the same
Core `interactions` table with explicit owner columns and a forward migration, but no
synthetic CapabilityRun or Node transport response. The Core-private planning request
model does not alter the M15 Contract's Run-owned `InteractionRequest`.
