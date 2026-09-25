# M20-D — ExecutionPlan and deterministic policy gate

## Goal and dependency

Convert one M20-C `PoCInspection` plus an explicit Mission target into structured execution
intent; validate it deterministically before any dependency installation, runtime preparation, or
PoC process launch. The Reasoner may **propose** a plan. Only Core validation and policy may
authorize it; the Node must enforce its local part. A model-generated plan is never an execution
token merely because it parses as JSON.

## Typed boundary and plan roles

| Input | Output |
| --- | --- |
| Hypothesis/candidate, pinned source `ArtifactRef`, inspection and classification, one `AssetRef`/optional `ServiceRef`, Mission scope, requested risk context | Contract `ExecutionPlan` in `DRAFT`, plus explicit proposed bindings and validation evidence |
| Draft plan and authoritative Core/Node facts | `VALIDATED`, `REJECTED`, or blocked pending a distinct policy approval/HITL prerequisite; reasons and decision provenance |

`PoCInspection` states what source analysis found or could not determine. `ExecutionPlan` states
**one intended execution**: source Artifact, location/runtime/version and isolation, explicit
entrypoint and argv-style target/parameter bindings, dependencies/build preparation, Resources
and Sessions, allowed network destinations and filesystem effects, `SecretRef`/`CredentialRef`
bindings, timeout, expected outputs/effects, evidence capture, cleanup, and uncertainties. It is
not a dump of all inspection findings or the evidence itself. The current Contract model already
contains source, runtime, isolation, dependencies, entrypoint, `argument_bindings`, Resource
refs, expected outcomes/effects, uncertainties, status, and provenance. It does **not** explicitly
represent all the above target/network/secret/cleanup constraints. During implementation, review
whether versioned Contract fields or a narrow Core-owned validated binding/permission envelope
is needed; do **not** bury enforceable rules in arbitrary `metadata` or rebrand a shell string as
`argument_bindings`. `WorkspaceRef` currently belongs to SDK runtime; it is not yet a Contract
reference. A Workspace path can never become plan identity.

Validation must check, against current authoritative state: Mission ownership of target and
evidence refs; target scope and allowed destinations; source hash/revision/availability; that the
entrypoint exists inside that exact source; runtime and classification support; dependency/build
declarations and provenance; secret/credential ownership and explicit grant intent; Resource/
Session prerequisites; no root/admin, forbidden side effects, or undeclared network/filesystem
behavior; finite timeout/limits; policy decision and approval provenance. Validation must also
ensure cited inspection facts actually support plan bindings. Revalidate mutable prerequisites
at Node acceptance/launch. A draft plan cannot smuggle a different target or source after
inspection. Keep executable as `executable + argv[]`; a required shell is an explicit assisted or
unsupported property, never string concatenation of README content.

Use existing `ExecutionPlanStatus` values (`DRAFT`, `VALIDATED`, `APPROVED`, `EXECUTED`,
`REJECTED`) without conflating them with `CapabilityRunStatus`. `APPROVED` is a distinct policy
decision, not a human Interaction response. Policy denial ends this path; a missing parameter may
request M15 assistance but cannot override denial. Persist plan version, validation rule version,
source hash, decision, reason codes, approver/provenance where applicable, and the exact target
binding; a later source/target change requires a fresh validation decision.

## Reuse, additions, and non-goals

Reuse Contract `ExecutionPlan`, typed refs and status, Core Mission/Asset/Service/Artifact/Secret
services, M19 advisory proposal-validation pattern, Node local scope enforcement, and existing
Router/transport. Add a Core deterministic plan validator and policy decision boundary; a
versioned plan persistence/migration is likely required. The current repository has no complete
PoC policy approval engine; M20-D must provide the **minimal reviewed, fail-closed** gate before
any automatic path is enabled. It must not grant a broad generic policy override.

No runtime install, process execution, model tool call, shell adapter, or automatic workflow
dispatch belongs to plan construction. No unreviewed change to Contract v1 is assumed here.

## Stop, security, and tests

Reject mismatch of input/source/target/mission, unknown plan field semantics, unsupported
runtime, ambiguous entrypoint, unresolved side effects, unbounded destination/timeout, invalid
credential grant, absent Resource, unavailable content, or missing policy. A validation error
must leave the source/inspection evidence intact. Do not normalize model mistakes into a valid
plan or silently grant a broader target.

Tests: all rejection cases above; separate DRAFT/VALIDATED/APPROVED transitions; stale source
hash and changed Mission scope; honest policy denial; schema validation; duplicate plan
evaluation without duplicate execution; Node refusing a forged/unvalidated plan; no direct
Reasoner-to-Process path. Manual review should display proposed vs validated intent and reasons
without secrets. **Done** when only an explicitly validated (and approved if required) plan can
reach a managed execution request, and revocation/staleness fails closed.

**OPEN DECISION (M20-D ADR required):** where explicit target/network/secret/cleanup fields live;
the minimal Core policy/approval persistence and token or permission-envelope shape; what local
Node enforcement can prove. Resolve these before implementing the automatic runtime.
