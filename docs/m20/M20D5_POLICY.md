# M20-D5 — Deterministic ExecutionPlan policy assessment

**Implemented; M20-D is CLOSED after D8 acceptance.** D5 assesses immutable v2 intent. It does not
approve, prepare, stage, dispatch or execute a plan. Production `execute_plan()` stays denied.

`CorePlanPolicyService.evaluate(plan_ref)` loads the finalized plan, its COMPLETED/VALID
PlanningAttempt and the single matching VALID `m20-d4-plan-validator@1` decision from Core.
Missing, invalid, stale-digest or unknown-version validation fails closed without a policy
assessment. The caller cannot provide a plan, validation or policy document to this method.
`get_assessment(decision_ref)` is historical lookup, not current authorization.

Core composition explicitly registers frozen `NarrowPolicyProfile` documents in
`PolicyProfileRegistry`. The initial requested identity is `m20-python-single-target@1`.
Registration requires a MissionRef and explicit allowed AssetRefs, with optional allowed
ServiceRefs; Mission ownership by itself never grants policy permission. Unknown or duplicate
profile identity is rejected, with no permissive fallback. The profile content's canonical
SHA-256 digest is pinned in every new assessment and in the decision-context prerequisite
digest; changed content cannot silently reuse an old assessment. Operators must treat profile
content/version changes as a new reviewed policy configuration, not as an invisible edit.

The pure `m20-d5-policy-evaluator@1` checks the typed plan and a Core-loaded current
Mission/Asset/Service reference/status snapshot. The narrow checker accepts only one explicit
Mission-owned TCP service endpoint, Python `>=3.12,<4` on attacker-side Linux/Kali, user-space,
noninteractive, declared standard-library/local-source dependencies, bounded read-only source,
one selected-target network rule, no public/callback/listener/multi-target intent, no
Secret/Credential or Resource/Session requirements, and finite wall/process/memory/output/write
budgets within the registered ceilings. Unknown or broad effects, filesystem mutation and
material policy mismatches are hard DENY. It neither probes a Node nor resolves dependencies,
secrets or source bytes. The profile's no-approval variant is used only in tests.

Hard mismatches produce `DENY` with bounded reason codes. Only a fully passing profile may
produce `REQUIRES_APPROVAL` if the profile requests human approval, or `ALLOW` otherwise.
`REQUIRES_APPROVAL` creates no `OperatorPlanApproval` or Interaction. `ALLOW` is still only an
assessment: readiness remains `NOT_ASSESSED`, authorization `NONE`; it is not a Run, Node token,
permission envelope or staging authority. D6 owns any later approval/HITL work, while E/F must
separately define and enforce actual execution admission.

The D2 append-only `plan_decisions` table persists assessment, exact plan/intent, profile
identity/version/digest, evaluator identity/version, Mission/scope, validation identity/digest,
classification digest and reference/status-only current scope snapshot through the decision
context fingerprint. Timestamps, Node availability and sensitive values are excluded from the
fingerprint. An unchanged context reuses its decision. Changed policy content, Mission assets,
Asset/Service status or validation identity yields a new fingerprint and immutable decision;
an old ALLOW remains history, never current permission. A new partial unique SQLite index
(`0014_m20_d5_policy_identity`) enforces at most one D5 checker assessment per plan/context
across independent Core processes while preserving older D2 policy-variant history.
D5 does not alter the
PlanningAttempt's VALID disposition or its immutable plan/validation.

Current limitation: the profile registry is explicit Core composition, not a database-backed
policy administration system. It is intentionally narrow; broader runtimes, dependencies,
effects or target classes require separate policy design and validation. No D5 decision proves
that future Node isolation can enforce the declared intent.
