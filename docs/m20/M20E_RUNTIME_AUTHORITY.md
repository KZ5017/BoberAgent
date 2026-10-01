# M20-E runtime preparation authority

**Status:** E1/E2 complete; E3 trusted Node admission implemented, real Core↔Kali acceptance pending. [ADR 0018](../adr/0018-m20-e-preparation-authority-and-applicability.md)

E3 accepts `runtime.prepare/prepare` only through the authenticated Core transport
boundary. On MCP, the existing verified bearer principal is checked independently of the
serialized permit. Local `execute_local()` and the generic invocation endpoint deny direct
preparation admission. The Node binds the exact Run, preparation, Mission, plan/intent,
Node/provider/version, source pins, profile, actions, validity window and serialized delivery
fingerprint into durable authority. Identical replay is accepted; conflicting replay is
rejected. Node restart preserves an admitted QUEUED Run only with its authority row.
is authoritative. M20-D is CLOSED; production `execute_plan()` remains denied.

## Owned records and flow

`RuntimePreparationAttempt` is Core-owned durable history, separate from the D2
`PlanningAttempt` and from a `CapabilityRun`. One preparation dispatch uses the existing
CapabilityRouter, `CapabilityInvocation`, CapabilityRunRef, neutral transport, Node Runtime,
Result outbox and Core ingestion. Core reconciles the Result and synchronized evidence; neither
transport delivery nor a successful process exit alone completes preparation. `runtime.prepare`
is the coherent capability identity. The Node implements its preparation provider behind SDK
boundaries; it does not own policy or the canonical attempt.

`RuntimePreparationSpec` is immutable, versioned, bounded input: exact plan/source pins,
profile/version, Node/provider, interpreter class, permitted operations and preparation limits.
It is not caller-supplied authority. `PreparationPermit` is a distinct immutable Core-issued
authorization for these actions only. A future execution authorization is another decision.
The permit and receipt are typed at the narrow shared boundary in E1; the Core attempt and
policy evaluation stay Core-private. E1 changes Contract schemas only, not transport schemas,
issuance or trusted admission. The SDK typed port is not production-backed yet.

## Admission and trusted path

Core must load the current authoritative D plan and decisions, not accept arbitrary payloads
as proof. Before issuing a permit it checks: strict current V2 plan and digest; VALID current
PlanValidation; current D5 assessment not DENY; exact currently applicable APPROVED D6 decision
if REQUIRES_APPROVAL; Mission and single-target scope; source C/B pins; preparation profile;
limits; and routable Node/provider capability and confinement support. Historical records are
not current authority. Unsupported requirement, uncertainty, or changed context is a typed
rejection, never a silent relaxed profile.

The permit binds MissionRef; PreparationRef and CapabilityRunRef; PlanRef and intent digest;
validation/policy/approval identities and policy-context fingerprint; selected Node/provider
identity/version; exact raw/manifest ArtifactRefs, SHA-256 and sizes and resolved commit;
profile/version/digest; permitted import/preparation actions and budgets; bounded validity
window and unique identity. It expressly grants no package/target/listener network, secrets,
or PoC execution. Node admission verifies authenticated sender, permit integrity and
all bindings before import or preparation. A raw digest or boolean does not authenticate an
issuer. The baseline real-carrier trust assumption is one exclusive, out-of-band configured
Core control bearer over TLS, verified by the Node's MCP authentication hook; in-memory tests
use one explicitly registered trusted Core peer. This authenticates the holder, not a signed
permit or multiple Core principals. If the Node admission adapter cannot obtain that verified
principal, E3 fails closed for review. A stolen/shared bearer is outside the claimed guarantee;
its value never enters permit/Result/log data. Tests must cover unauthenticated, wrong-principal
and mismatched-principal import/invocation as well as replay.

`PlanValidation != PlanPolicyAssessment != OperatorPlanApproval != PreparationPermit !=
ExecutionAuthorization`. Operator approval after plan finalization does not reopen the
PlanningAttempt. It never creates execution authorization.

E2 reserves one future `CapabilityRunRef` on each eligible Core preparation attempt and its
permit. It intentionally creates no `CapabilityRun` row: in the current runtime model that
row would imply executable work before E3's authenticated admission/dispatch exists. D5's
composition-owned profile must be present and an exactly current assessment must already
exist. E2's read-only check never turns historical ALLOW into a fresh assessment. Rejected
attempts have no permit or Run reservation. Historical permit lookup is not a dispatch gate;
`current_admission()` rechecks the current D, source and provider context and permit interval.

## Lifecycle, identity and applicability

| Core attempt | Meaning |
| --- | --- |
| REQUESTED | Durable request and fingerprint; no dispatch proven. |
| DISPATCHED | Stable CapabilityRunRef selected/submitted; uncertain delivery is reconciled, not blindly retried. |
| AWAITING_ARTIFACT | Terminal successful Result/receipt exists; required manifest is not yet Core-verified. |
| COMPLETED | Exact manifest accepted and resource identity recorded. Historical fact only. |
| REJECTED / FAILED / INTERRUPTED / CANCELLED | Terminal explicit stop with safe typed reason. |

No initial WAITING_INPUT/WAITING_RESOURCE. Attempts and permit issuance are append-only
authority history. The request fingerprint includes exact plan/context/source/profile/limits
and selected provider/Node. Replaying an identical request returns the same determination and
RunRef, never a new dispatch. Conflicting reuse of an identity fails. A different explicit
attempt has a new ref; there is no automatic retry of uncertain work.

Current availability/applicability is a separate projection: at least current D decision
context, Node/provider health, permit validity for new work, Resource existence and integrity,
manifest evidence and scope must still agree. A historical COMPLETED row is not rewritten when
the Node goes offline. Reuse requires both identical request/context and a currently available
reverified Resource. [Recovery rules](M20E_PREPARATION_RECOVERY.md) define conservative stops.

## E/F handoff

The accepted handoff is immutable `PlanRef + intent digest + Node identity + ResourceRef +
accepted RuntimePreparationManifest identity/digest`. F must obtain separate current execution
authorization and revalidate D applicability, Resource lease, source/entrypoint/runtime
integrity, target/network scope, F budgets and separately authorized secrets. E's permit cannot
be promoted into F authority. No E process executes source. See
[ADR 0020](../adr/0020-m20-e-trusted-python-preparation-boundary.md).
