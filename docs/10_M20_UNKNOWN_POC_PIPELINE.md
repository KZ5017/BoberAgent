# Milestone 20 — Generic Unknown PoC Pipeline

**Status:** Normative implementation plan; M20-A is implemented and **M20-B — Acquisition +
Immutable Provenance is CLOSED**. B1–B4 established the bounded acquisition path; B5 validated
it against real public GitHub through a Kali Execution Node, TLS/MCP, Node→Core Artifact sync,
Core finalization, and Core reopen without re-fetch. **M20-C — Source Inspection + Conditional
Support Classification is CLOSED** following successful operator C4 acceptance with C1@1,
C2@2 and C3@2. C5 is optional advisory future work, not a closure prerequisite.
**M20-D — ExecutionPlan + Deterministic Validation/Policy is CLOSED.** D1–D6 implement
typed intent, durable admission/construction, validation, policy and Core-owned assistance/
approval. D7 synthetic vertical acceptance and operator-run D8 real retained-source negative
acceptance both passed. **M20-E architecture is SPECIFIED; E1 typed contracts are COMPLETE;
E2–E9 have NOT STARTED; M20-E remains OPEN; M20-F has NOT STARTED.** See the
[M20-D closure record](m20/M20D_IMPLEMENTATION.md#m20-d-closed-real-retained-source-negative-acceptance) and the
[retained-source acceptance record](m20/M20C_IMPLEMENTATION.md#m20-c-closed-real-retained-source-acceptance).
ADR 0014 fixes M20-B architecture; [ADR 0015](adr/0015-m20-c-source-inspection-ownership-evidence-and-authority.md)
fixes M20-C inspection ownership, evidence, and authority before implementation.
This plan refines `09_BOOTSTRAP_PLAN.md` §100 without changing the Capability, Core, or Execution Node ownership
rules. Implement M20-A through M20-H incrementally, but judge M20 as one milestone.

## Purpose and starting boundary

Given a Core-owned `VulnerabilityHypothesis` for **one explicit, in-scope Mission target**, find
candidate public reproductions, preserve provenance, inspect untrusted source, derive and validate
an `ExecutionPlan`, prepare an approved attacker-side runtime, execute only a supported class,
capture evidence, interpret the result, attempt only bounded adaptation, and request human
assistance when the supported boundary is exceeded. Input includes a `MissionRef`, an `AssetRef`
and optionally `ServiceRef`, supporting `ObservationRef`s, observed product/technology and version
evidence (including unknown versions), and a vulnerability identifier **or** a descriptive
hypothesis. A search result is not a vulnerability finding or permission to execute.

M20 does **not** discover arbitrary vulnerabilities, search until something exploitable appears,
run arbitrary model-generated commands, or execute every acquired PoC. It does not make the LLM,
GitHub, or a particular exploit tool the architecture. Research asks what might reproduce **this**
hypothesis; scope and the selected target never expand implicitly.

## Invariants and ownership

1. Core owns Mission scope, `VulnerabilityHypothesis`/`PoCCandidate` meaning, decision and policy,
   validated plan, Workflow/Attempt provenance, interpretation, and canonical World State. The
   Reasoner may propose typed interpretations or plans, but cannot authorize or dispatch them.
2. The Execution Node owns managed Workspace/Resource/Process execution and local Artifact spool.
   Capability implementations use the SDK; Core does not import PoC adapters. The existing
   Router and neutral transport carry invocations/results; MCP remains only a carrier.
3. Acquired README, source, package metadata, issues, and model-visible excerpts are **untrusted
   data**, never instructions. No README command is directly executed. No silent source editing,
   parameter repair, dependency installation, scope expansion, or exploit-logic modification.
4. The inspected source revision and executed bytes must be the same pinned, hashed Artifact.
   Scope, target binding, runtime constraints, side effects, and policy are checked before
   execution and again where the Node can enforce them. Re-fetching a mutable branch is forbidden.
5. Preserve raw acquisition and execution evidence as Artifacts. Research claims and PoC output
   are not automatically Observations proving a target vulnerable, Findings, or global Knowledge.
   Execution status and semantic outcome remain separate; `UNKNOWN` is valid.
6. Durable records normally contain `SecretRef`/`CredentialRef`, not values. Only the existing
   authorized Run boundary may resolve values needed by a tool. Logs and Reasoner context remain
   redacted. Human assistance cannot override a policy denial.

## Typed stage boundaries

| Stage | Planned input → output | Owner and rule |
| --- | --- | --- |
| Research | `VulnerabilityHypothesis` → bounded `ResearchRequest` → sourced hits / `PoCCandidate`s | Core-owned `ResearchProvider` port and admission; no download-as-execution |
| Acquire | selected candidate + historical source hit → Core `PoCAcquisition`, full-SHA GitHub ZIP Artifact + structural manifest Artifact | Core authorizes/routes/finalizes only after both Artifacts sync and verify; Node resolves/retrieves/inventories without execution |
| Inspect | completed acquisition's exact Core-retained raw ZIP + structural manifest → versioned `PoCInspection` + conditional classification and reasons | Core-owned, read-only, deterministic-first; rehash and cite verified bytes; optional later advisory Reasoner; no PoC execution or plan |
| Plan | inspection + target → Core proposal/revisions → immutable ExecutionPlan v2 | Core constructs intent, no side effects |
| Validate | intent → separate validation, policy assessment, optional operator approval | Core decisions; STOP, not execution authorization |
| Prepare | exact intent + current decisions + PreparationPermit + retained raw/manifest Artifacts → runtime Resource, immutable manifest/receipt | Core attempt/admission; neutral Core→Node Artifact Import; routed `runtime.prepare`; Node enforcement; Core evidence reconciliation; no install/entrypoint |
| Execute | exact intent + accepted preparation evidence + separate F execution authorization → managed evidence and `CapabilityResult` | Future Node execution gate; `execute_plan()` remains denied in E |
| Interpret | plan + evidence + relevant state/Knowledge → bounded interpretation | Core; do not equate exit code with vulnerability confirmation |
| Adapt/HITL | interpretation → one bounded declared adjustment, durable request, or stop | Core Workflow/Attempt + M15 Interaction; policy approval separate |

These are semantic boundaries, not a promise that M11's static sequential Workflow currently
supports dynamic branching. M20 implementation must either extend Core-owned durable orchestration
under review or compose explicit phases without bypassing the Router. Each transition requires
persistent identity, provenance, and idempotency; no indefinite in-memory coroutine is the source
of truth.

## M20-v1 support boundary

`AUTOMATIC` is conditional eligibility, **not** a finding or blanket approval: attacker-side,
source-visible, single-target, user-space, non-interactive Python with explicit entrypoint and
target parameters; no root/admin, source modification, undeclared dependency/build action, or
unbounded filesystem/network effects; output must be deterministically checkable or honestly
interpretable. Core policy and Node enforcement must exist before this class can run. A venv
isolates dependencies, not hostile code or network access. `ASSISTED` identifies a concrete
missing prerequisite through existing Resources, Sessions, Secret refs, or M15 Interaction.
`UNSUPPORTED` means no automatic M20-v1 execution for high-risk or unbounded classes; it does not
claim permanent impossibility. See [the support matrix](m20/00_SCOPE_AND_SUPPORT_MATRIX.md).

The initial location is the **Kali attacker-side Execution Node**, targeting one explicitly
authorized Mission Asset. Future remote-Session, target-side, Windows or Linux target runtimes may
be representable in plan intent but have no M20-v1 automatic adapter.

## Phase map

| Phase | Implementation plan | Completion gate |
| --- | --- | --- |
| M20-A | [Research and candidates](m20/01_RESEARCH_AND_CANDIDATES.md) | bounded, sourced candidates; no acquisition/execution |
| M20-B | [Acquisition and provenance](m20/02_ACQUISITION_AND_PROVENANCE.md) | pinned, hashed Artifact; no execution |
| M20-C | [Inspection and classification](m20/03_INSPECTION_AND_CLASSIFICATION.md) | **CLOSED:** typed facts, explicit reasons, fail-closed uncertainty; calibrated real C4 accepted |
| M20-D | [ExecutionPlan and policy](m20/04_EXECUTION_PLAN_AND_POLICY.md) | **CLOSED:** D1–D8, synthetic D7 and real retained-source negative D8 accepted; STOP before permission/dispatch |
| M20-E | [Runtime preparation](m20/M20E_IMPLEMENTATION.md) and [E/F boundary](m20/05_RUNTIME_PREPARATION_AND_EXECUTION.md) | **Architecture SPECIFIED; E1 COMPLETE, E2–E9 NOT STARTED, overall OPEN:** typed preparation-only boundary exists, but no permit issuance, source import, runtime or execution |
| M20-F | [Controlled execution](m20/05_RUNTIME_PREPARATION_AND_EXECUTION.md#m20-f-execute-and-capture-evidence) | **NOT STARTED:** separate execution authorization, managed evidence and honest Result |
| M20-G | [Interpretation, adaptation, HITL](m20/06_INTERPRETATION_ADAPTATION_AND_HITL.md) | separate outcome, bounded attempts, durable wait/stop |
| M20-H | [Vertical smoke and acceptance](m20/07_VERTICAL_SMOKE_AND_ACCEPTANCE.md) | controlled fixture then authorized real unknown PoC |

## Existing foundation and implementation gaps

Reuse Contract `ExecutionPlan`, `CapabilityResult`, Artifacts, SDK `ExecutionContext`, managed
Workspaces/Processes, Node spool, Artifact sync, Registry/Router, M11 durable Workflow, M15
Interaction, M16 run-scoped secret grants, M17/18 curated Knowledge, and M19 advisory Reasoner.
Legacy plans remain decodable but their status is not authority. D1 adds deeply immutable v2
intent with explicit source, targets, runtime, bindings, ordered invocation, requirements,
filesystem/network constraints, budgets and expected evidence. D3 admits authoritative persisted evidence; D4 constructs and validates only the narrow reviewed Python/single-endpoint slice. D5 adds a Core-owned narrow deterministic policy assessment, not approval or authorization. The production
Node's `execute_plan()` currently denies execution. Current M11 Workflow is static and sequential;
M19 Reasoner validates proposals but has no PoC inspector or executor. A complete PoC policy
execution authorization and runtime confinement are not present. C1–C3 now provide immutable PoC Inspection history,
exact evidence, deterministic observations and conditional support; these do not authorize execution.
Do not hide these gaps in opaque `metadata` or call existing local process execution a sandbox.

The accepted M15 implementation cannot reconstruct a waiting Python continuation after a Node
restart; the waiting Run fails conservatively. Future PoC resume claims need explicit checkpoint
work and tests. An InteractionRequest supplies missing information, **not** policy approval.
Unapproved or unenforceable plans stop before preparation/execution.

## Definition of M20 completion

All phase contracts, persistence/migrations where needed, ownership and policy enforcement,
replay-safe transitions, evidence integrity, negative/unknown semantics, and architecture tests
must be implemented. A harmless local fixture must traverse the entire path without shortcuts;
then one previously unknown real public repository must be pinned, inspected, and run only against
an explicitly authorized controlled lab target. Unsafe/ambiguous classes must stop at their
documented boundary. No real PoC or research provider is selected by this planning package.

## Authoritative references

Read [system architecture](01_SYSTEM_ARCHITECTURE.md), [Capability Contract](02_CAPABILITY_CONTRACT.md),
[SDK](03_CAPABILITY_SDK.md), [World State](04_WORLD_STATE_MODEL.md),
[Workflow/Reasoning](05_WORKFLOW_AND_REASONING.md), [Knowledge](06_KNOWLEDGE_SYSTEM.md),
[Execution Node](07_EXECUTION_NODE.md), and [reference PoC capability](08_REFERENCE_CAPABILITIES.md)
with this plan. Accepted ADRs [0005](adr/0005-durable-sequential-workflow-execution.md),
[0008](adr/0008-durable-human-interaction.md), [0009](adr/0009-core-secrets-and-run-scoped-grants.md),
[0010](adr/0010-file-backed-knowledge-foundation.md),
[0011](adr/0011-derived-semantic-retrieval.md), and
[0012](adr/0012-bounded-advisory-reasoner.md) describe currently implemented limits.
[ADR 0013](adr/0013-m20-research-ownership-and-candidate-identity.md) fixes M20-A research
ownership, hypothesis, query and candidate identity. [ADR 0014](adr/0014-m20-acquisition-ownership-and-immutable-source-representation.md)
fixes M20-B acquisition ownership, selected-hit binding, immutable source representation,
provenance and finalization. [ADR 0015](adr/0015-m20-c-source-inspection-ownership-evidence-and-authority.md)
fixes M20-C inspection ownership, exact source binding, citations, fact authority, durable
history, and conditional classification. M20-C is CLOSED with authoritative
`m20-c2-deterministic@2` / `m20-c3-support-classifier@2`; historical @1 results remain
immutable. The real source classified UNSUPPORTED, not safe or authorized to execute.
C5 remains optional/deferred and is not required for M20-C closure.
[ADR 0016](adr/0016-immutable-execution-intent-and-policy-authority.md) fixes immutable intent
and separate authority; [ADR 0017](adr/0017-core-owned-durable-planning-interactions.md) fixes
later D6 Interaction ownership. D1 adds typed intent; D2 adds Core-owned immutable plan/decision history, atomic request reuse,
revision CAS and explicit persistence recovery through migration 0013. D3 verifies Mission/source/C2@2/C3@2 ownership, versions, configuration and exact parent/digest
pins without reopening source bytes. AUTOMATIC/ASSISTED remain REQUESTED and eligible only for
construction/assistance; UNSUPPORTED becomes durable COMPLETED/UNSUPPORTED with exact C3
reasons and no proposal, plan or decision. Invalid provenance fails before attempt creation.
Identical requests reuse D2 history atomically across restart/concurrency. D4 now persists reviewed
proposal revisions and atomically finalizes immutable V2 plus separate validation for the narrow
synthetic positive case; invalid input has no plan and bounded input gaps may wait without HITL.
D4 leaves policy NOT_EVALUATED. D5 evaluates a registered Mission/target-scoped profile and appends
ALLOW, DENY or REQUIRES_APPROVAL as history; readiness stays NOT_ASSESSED and authorization absent.
D6 now adds bounded assistance and separate exact policy approval without reopening finalized
attempts; [D6 details](m20/M20D6_PLANNING_HITL.md). E architecture is specified in
[ADRs 0018](adr/0018-m20-e-preparation-authority-and-applicability.md),
[0019](adr/0019-m20-e-immutable-source-import-and-prepared-resource.md), and
[0020](adr/0020-m20-e-trusted-python-preparation-boundary.md), with the
[E1–E9 slice plan](m20/M20E_IMPLEMENTATION.md). E1 typed contracts are implemented; E2–E9
and F have not begun.
Even VALID + ALLOW + operator approval is not preparation or execution authorization. E must
issue a separate PreparationPermit bound to exact digest, Mission, action, Run, Node/provider,
source, profile and limits. F must separately authorize execution and revalidate current
applicability. E implementation and Kali confinement-backend validation remain open; F's
execution gate is not specified by E.

D7 now proves six offline, migration-backed D3→D6 vertical cases using synthetic
retained evidence and production Core pumps: automatic ALLOW; exact bounded planning
assistance; approval and operator denial; hard policy DENY; and material UNKNOWN
rejection. Reopen/reuse, stale/conflicting replay, immutable history, context invalidation
and zero new execution authority are asserted. The [D7 acceptance record](m20/M20D_IMPLEMENTATION.md#d7--synthetic-vertical-acceptance)
is not a real-source, runtime or safety claim.

The operator completed D8 against the retained CERTCC C2@2/C3@2 chain: Core D3 produced
`COMPLETED / UNSUPPORTED / REJECTED_UNSUPPORTED`, preserved the authoritative C3 reasons,
and created no plan, decision, Interaction or execution-side record. Core reopen and identical
admission reuse passed; upstream acquisition and inspection history remained unchanged.
This negative classification is not safety or authorization. Planning validity, policy,
operator approval, preparation permit and execution authorization remain separate. Production
`execute_plan()` is denied. M20-E architecture is specified; only E1's pure typed boundary is
implemented. E2–E9 and M20-F have not begun. **M20-D is CLOSED.**
