# ADR 0018: M20-E preparation ownership, authority and applicability

**Status:** Accepted for M20-E architecture. E1 typed boundary is complete; E2+ behavior has not begun.

## Decision

Core owns a durable `RuntimePreparationAttempt`, its admission decision, and a distinct,
immutable `PreparationPermit`. Node work is a normal `runtime.prepare` CapabilityRun selected
through the Core CapabilityRouter. The Node enforces the permit at its trusted admission
boundary before Artifact Import, workspace allocation, or preparation. Neither Core nor the
transport runs the provider directly. An authenticated channel and Node-controlled verifier
must bind the permit to this invocation; a digest or caller-supplied `authorized` boolean is
not a credential. For the initial real MCP carrier, the Node treats its explicitly configured,
exclusive Core control bearer over TLS as the issuing principal; permit admission, Artifact
Import and invocation must each authenticate as that principal. In-memory tests bind one
explicitly registered trusted Core endpoint. This is a single-principal deployment assumption,
not a standalone signature or multi-tenant trust model: anyone holding that bearer can
impersonate Core. No permit is accepted from an unauthenticated or differently configured
transport peer. E3 must test principal binding and replay at both import and invocation;
if the deployed MCP adapter cannot expose that authenticated principal to Node admission, E3
stops for review instead of trusting a JSON field. Credentials stay out of permits and logs.

Permit issuance requires a current strict `ExecutionPlanV2` and intent digest, a currently
applicable VALID PlanValidation, a current D5 assessment other than DENY, exact applicable
APPROVED OperatorPlanApproval when D5 requires it, and a separate successful preparation-
profile admission. Core re-evaluates Mission/scope, source and inspection pins, validation,
policy/profile context, approval, provider/Node availability, and preparation budgets at
issuance. Historical D records alone confer no authority. A DENY or missing approval stops.

The permit binds MissionRef, PreparationRef, preparation CapabilityRunRef, PlanRef plus intent
digest, validation/assessment identities, policy/context fingerprint, approval identity if
needed, Node and provider identity/version, exact raw and manifest ArtifactRefs/hashes/sizes,
resolved commit, preparation profile/version/digest, actions, limits, validity window, and
admission nonce/identity. Its action set is closed to approved import and preparation. It
explicitly excludes target/listener/package network and target-secret authority. Core retains
permit issuance history; Node validates the complete binding, expiry, version, and duplicate
identity and rejects conflicting replay. Permit content is not an execution authorization.

The Core attempt lifecycle is `REQUESTED → DISPATCHED → AWAITING_ARTIFACT → COMPLETED`,
with terminal `REJECTED`, `FAILED`, `INTERRUPTED`, `CANCELLED`. `AWAITING_ARTIFACT` means a
successful terminal CapabilityResult exists but the exact preparation evidence is not yet
durably accepted by Core. No initial `WAITING_INPUT` or `WAITING_RESOURCE`: unsupported
prerequisites fail explicitly. Terminal attempts are historical and never reopened.

Request fingerprints bind the exact plan, D context, source, profile, limits and selected
provider/Node; they support identical request reuse without creating a second Run. Distinct
attempts receive distinct refs/RunRefs. A completed historical attempt is reusable only when
the same request/context still has a currently available and reverified prepared Resource.
Current applicability/availability is a projection, never a rewrite of historical completion.
Uncertain dispatch cannot be retried as a new Run automatically. Core reconciles durable
Run/Result/outbox and Node state; unprovable work becomes INTERRUPTED.

`PlanValidation != PlanPolicyAssessment != OperatorPlanApproval != PreparationPermit !=
ExecutionAuthorization`. M20-F requires its own current execution authorization even when
preparation completed. Production `execute_plan()` remains denied throughout M20-E.

## Rejected alternatives

- Treating VALID, ALLOW, or operator approval as an implicit Node token.
- Treating a typed digest or transport message as self-authenticating authority.
- Letting the Node derive Core policy from source or independently choose target/provider.
- Reopening a completed PlanningAttempt to wait for preparation.
- Sharing mutable preparation state across distinct attempts or blindly retrying uncertain work.

## Consequences

E1 defines typed boundaries; E2 persists Core attempts/admission; E3 implements authenticated
Node admission. No D migration/history is rewritten. Preparation can end with a verified
Resource but no right to execute a PoC. See [runtime authority](../m20/M20E_RUNTIME_AUTHORITY.md).
