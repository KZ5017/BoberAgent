# Milestone 20 — Generic Unknown PoC Pipeline

**Status:** Normative implementation plan; M20-A research and the offline M20-B1 acquisition
foundation are implemented. ADR 0014 fixes M20-B architecture; B2–B5 and M20-C through M20-H
remain planned. This plan refines
`09_BOOTSTRAP_PLAN.md` §100 without changing the Capability, Core, or Execution Node ownership
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
| Inspect | acquired Artifact → `PoCInspection` + classification and reasons | deterministic inspection, optionally bounded advisory Reasoner; no PoC execution |
| Plan | inspection + selected target → proposed Contract `ExecutionPlan` and explicit bindings | Core validates against authoritative refs, source, scope and policy |
| Validate | draft plan → validated plan / rejection / assistance or approval requirement | deterministic Core gate; Node revalidates enforceable constraints |
| Prepare | validated/approved plan → isolated attacker-side runtime Resource + Workspace | Node; pinned source/dependencies, no README install command |
| Execute | validated plan + runtime → managed process evidence and `CapabilityResult` | Node via SDK `ProcessService.execute_plan`; no shell string by default |
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
| M20-C | [Inspection and classification](m20/03_INSPECTION_AND_CLASSIFICATION.md) | typed facts, explicit reasons, fail-closed uncertainty |
| M20-D | [ExecutionPlan and policy](m20/04_EXECUTION_PLAN_AND_POLICY.md) | deterministic validation; no model authority |
| M20-E/F | [Runtime preparation and execution](m20/05_RUNTIME_PREPARATION_AND_EXECUTION.md) | enforceable isolation and managed evidence capture |
| M20-G | [Interpretation, adaptation, HITL](m20/06_INTERPRETATION_ADAPTATION_AND_HITL.md) | separate outcome, bounded attempts, durable wait/stop |
| M20-H | [Vertical smoke and acceptance](m20/07_VERTICAL_SMOKE_AND_ACCEPTANCE.md) | controlled fixture then authorized real unknown PoC |

## Existing foundation and implementation gaps

Reuse Contract `ExecutionPlan`, `CapabilityResult`, Artifacts, SDK `ExecutionContext`, managed
Workspaces/Processes, Node spool, Artifact sync, Registry/Router, M11 durable Workflow, M15
Interaction, M16 run-scoped secret grants, M17/18 curated Knowledge, and M19 advisory Reasoner.
The current Contract plan holds source Artifact, runtime, isolation, dependencies, entrypoint,
bindings, resources, outcomes/effects, uncertainty, status, and provenance; it does **not** yet
encode every proposed target/network/secret/cleanup constraint as explicit fields. The production
Node's `execute_plan()` currently denies execution. Current M11 Workflow is static and sequential;
M19 Reasoner validates proposals but has no PoC inspector or executor. A complete PoC policy
approval engine, runtime confinement, and PoC Candidate/Inspection persistence are not present.
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
provenance and finalization. M20-C and later-phase architecture decisions remain open.
