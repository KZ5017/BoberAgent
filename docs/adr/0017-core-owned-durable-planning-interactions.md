# ADR 0017: Core-owned durable planning interactions

**Status:** Accepted architecture; implementation deferred to M20-D6.

## Decision

Interaction will support two explicit owners: CapabilityRun and PlanningAttempt. Reuse
InteractionRef, bounded prompt types/response validation, immutable responses and replay
semantics. Core planning needs no synthetic execution Run or Node continuation. D6 implements
the ownership extension through forward migrations and compatibility tests, not a second HITL.

Core will persist planning waits and reconcile answers through explicit pumping, independent
of a live Python coroutine. Answers are revision provenance, not OBSERVED source facts.
Duplicate/replayed answers cannot create conflicting revisions or dispatch. Secret answers use
refs. Human assistance is not policy approval; neither is execution authorization.

## Compatibility and deferral

D1 introduces answer provenance types only. It changes no InteractionRequest, Node/Run behavior,
prompt, routing, response storage or resume machinery. M15 still fails waiting Runs conservatively
after Node restart; it cannot restore Python continuations. Core planning durability does not
imply runtime continuation restoration. E/F/G must separately review checkpoint-driven re-entry.

## Rejected alternatives

- Synthetic waiting execution Runs or Node-owned planning prompts mix ownership/lifecycle.
- A parallel HITL framework duplicates identity, validation and replay behavior.
- Treating an answer as approval/permission bypasses the separate policy boundary.
