# ADR 0013: Permanently reject the Generic Unknown PoC Pipeline

- Status: Accepted — explicit project-owner decision
- Date: 2026-11-17

## Context

The original architecture and Bootstrap Plan described Milestone 20 as an integrated generic
pipeline for researching unknown external PoCs, acquiring and inspecting source, generating an
ExecutionPlan, preparing a runtime, executing the source, interpreting results and adapting it.
The current branch starts at the M19 checkpoint `5218a41c3960383b1414114abecf52c038f27674`,
before M20 implementation. Those forward requirements conflict with the owner's current direction.

## Decision

**Milestone 20 — Generic Unknown PoC Pipeline is permanently rejected and removed from the
development plan.** This is not postponement, suspension or a lower-priority backlog item.
The former integrated pipeline is not a platform requirement, acceptance condition or prerequisite
for any other development. Earlier instructions to implement it are inactive. Restoring it, including
under another name or as an implicit dependency, requires a new explicit project-owner decision.

This decision rejects that development concept, not authorized penetration testing in general.
The accepted M1–M19 capabilities, component ownership, transport boundaries, evidence handling,
World State, Workflow, Knowledge, Reasoner and human-interaction contracts remain in force.

## Consequences

- Remove the former pipeline and its execution/adaptation acceptance cases from active normative
  requirements and milestone summaries. Preserve the M20 number as a short rejection record.
- Preserve generic Artifact, Resource, Session, ExecutionPlan and policy concepts. Their presence
  does not require an unknown-PoC pipeline or create execution authority.
- Repository inspection found the existing Contract `ExecutionPlan` model and tests, the SDK
  `ProcessService.execute_plan()` interface/fake, and the Node's explicitly denied production
  method. These are retained M1–M19 primitives, not an implemented M20 pipeline; no source removal
  or runtime change is part of this decision. Production `execute_plan()` remains denied.
- Passive evidence may contain source code or PoC material. Its provenance, immutability and
  separation from reusable Knowledge remain applicable; storing evidence does not authorize execution.
- ADRs 0001–0012 and historical implementation facts are preserved. No substitute roadmap,
  replacement pipeline, new capability, schema or migration is authorized here.

The [Bootstrap Plan](../09_BOOTSTRAP_PLAN.md#100-milestone-20--permanently-rejected) and
[agent instructions](../../AGENTS.md#current-project-direction) apply this decision to future work.
