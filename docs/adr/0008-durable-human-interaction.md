# ADR 0008: Durable human interaction suspension and resumption

- Status: Accepted for Milestone 15
- Date: 2026-09-22

## Context

Some finite Capability Runs need bounded operator input before they can continue. Blocking on a
private console would bypass Core, disappear on restart, and couple capability code to a user
interface. Conversely, persisting a Python coroutine cannot make suspended execution restorable.
The platform therefore needs durable request/response truth while remaining honest about the
limits of live execution state.

## Decision

A capability creates a Contract `InteractionRequest` only through
`ExecutionContext.interactions.request()`. The Execution Node atomically persists that request and
moves its owning Run to `WAITING_INPUT`, then emits an `interaction.requested` Event through its
existing durable outbox. Core projects that Event into a durable operator-facing Interaction
record. The response is persisted in Core before delivery through the neutral interaction
transport, and the Node validates and durably accepts it before waking the one live waiter and
returning the Run to `RUNNING`.

`InteractionRequest.requested_at` is the durable activation time: the instant the Node accepts the
request for persistence and makes the Run `WAITING_INPUT`. It is not the time capability code
happened to construct a request object. The Node finalizes this value with its injected runtime
clock, and the same immutable timestamp is stored in Node persistence, emitted in the request
Event, projected by Core, and shown to operators. Duplicate handling and response acceptance never
rewrite it.

Milestone 15 supports `CONFIRMATION`, bounded `TEXT`, and `SINGLE_CHOICE`. Requests are immutable,
correlated to one Mission and Capability Run, and may optionally carry Workflow correlation.
Responses are immutable: an identical replay is acknowledged idempotently, while a different
second response, cross-Run response, cross-Mission request, or response to a terminal request is
rejected. Request Events may contain prompts, choices, and schemas; response values are never
emitted as Events.

Core restart is supported while the Node and its live capability task remain running. Core can
rebuild the pending operator view from its database and retry a previously persisted response
intent without changing its timestamp or value. A Node restart cannot reconstruct a Python
continuation, so a previously waiting Run becomes conservatively `FAILED`, its Interaction becomes
`CANCELLED`, and late responses are rejected. Graceful task cancellation similarly produces a
terminal cancelled Result rather than fabricating resumption.

The Workflow Engine is unchanged: while its Capability Run has no terminal ingested Result, the
Workflow Run remains `RUNNING` and its Step remains `ACTIVE`. Explicit workflow pumping and normal
Result ingestion resume progression only after the capability actually completes.

## Consequences

- The Node remains authoritative for live suspension and resumption; Core owns the durable
  operator index and response intent.
- The neutral protocol gains one response operation. MCP is only its carrier; no UI or transport
  types enter the Capability Contract or SDK.
- No expiry scheduler is claimed in M15. Cancellation and non-restorable restart are explicit
  terminal paths.
- Plain `TEXT` responses are non-secret operator input. Secret entry, policy approval, interactive
  shells, distributed continuation restoration, and Human Interaction Resources/Sessions remain
  out of scope.
