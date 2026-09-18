# ADR 0005: Durable sequential Workflow execution

- Status: Accepted for Milestone 11
- Date: 2026-09-18

## Context

Core must sequence capabilities without depending on an LLM, an in-memory coroutine, a concrete
transport, or an Execution Node implementation. A Core restart can occur before dispatch, after
dispatch, or after durable Result ingestion. Re-evaluation must not create a second logical
CapabilityRun for the same Workflow step.

## Decision

M11 stores the immutable `WorkflowDefinition` with its `WorkflowRun` and stores one ordered
`WorkflowStepRun` per static step. Every Step Run maps to exactly one deterministic
`CapabilityRunRef`, derived with UUID5 from `(WorkflowRunRef, step_id)`. Core persists the
CapabilityRun and marks the step `PREPARED` before invoking `CapabilityRouter`; it marks the step
`ACTIVE` only after transport submission is accepted.

Ordinary reevaluation of an `ACTIVE` step only inspects durable Result Ingestion state and never
redispatches it. A process crash in the narrow `PREPARED` dispatch window may cause the same
transport invocation to be redelivered, using the same CapabilityRun identity and the existing
transport/Node deduplication semantics. It never creates a second CapabilityRun. A recorded routing
decision is reused rather than selecting a different provider.

M11 supports two explicit semantic success policies: `SUCCESS_ONLY` and
`SUCCESS_OR_NEGATIVE`. Execution failure, timeout, cancellation, `PARTIAL`, and `UNKNOWN` fail the
minimal sequential workflow. There is no implicit retry or fallback provider selection.

## Consequences

Workflow advancement is explicitly pumped and restart-safe without a scheduler. Definitions and
step inputs are JSON-compatible data, not executable expressions. Scope/entity projections are
built from Mission-owned Assets and still pass through the normal transport boundary and Node SDK
enforcement. Branching, loops, parallelism, dynamic bindings, remote cancellation, Goal evaluation,
and automatic retry remain deferred.
