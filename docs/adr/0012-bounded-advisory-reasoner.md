# ADR 0012: Bounded advisory Reasoner in Core

Status: Accepted for Milestone 19.

## Decision

Core owns a replaceable `ReasonerProvider`, an explicit-selection `ContextBuilder`, structured
`InterpretationResult`/`ActionProposal`, and a `ProposalValidator`. The first provider uses only
OpenAI-compatible `POST /v1/chat/completions` with `response_format.type=json_schema`. It accepts
configuration injected by an operator/application entrypoint; it does not read `.env.local` or
discover/load models. An injected HTTP client makes normal tests deterministic.

The builder selects one Mission Goal and Asset, related materialized Services and specified
Observation/Run refs, one active canonical Procedure, selected canonical/semantic Knowledge, and
specified available Capability metadata. It does not hydrate raw Observation values, Artifacts,
Secret bytes, Goal parameters, or whole repositories. Semantic chunks from a common source are
grouped in source order; duplicate source text is omitted after canonical inclusion. A deterministic
character budget admits higher-authority context first and reports included/omitted counts. Source
identity, revision, chunk ordinal, and provenance remain attached to included text.

Selected available Capability operations carry their complete inline input schemas from the
advertised CapabilityDefinition. Operations with unavailable or conflicting provider schemas are
not exposed; a capability entry and all its operation schemas are admitted or omitted atomically
by the lower-priority context budget. An ActionProposal must explicitly include an `inputs` object,
even if a particular operation accepts `{}`. Proposal-level target refs do not substitute for
operation input refs. Core never fills missing model inputs; ProposalValidator still checks the
authoritative operation schema and may reject an explicit but incomplete object.

The provider validates a complete structured response. Core then checks cited refs, Mission
ownership, current provider availability, operation identity, and inline operation JSON Schema.
External schema references are not fetched. Proposed Secret/Credential refs are checked as refs;
ordinary proposed input fields cannot carry recognized plaintext-secret fields. A validated
proposal is still not an invocation or approval. The service has no Router/transport/Workflow
dependency and cannot create a CapabilityRun.

## Consequences and limits

M19 returns structured result and provenance to its caller but adds no persistent Decision table or
automatic scheduler. A later Core decision/approval path must independently decide whether to act.
The context budget counts included serialized items, not tokenizer-specific tokens. Curated
Knowledge remains subject to human source review; no generic scanner can prove arbitrary prose
contains no sensitive material. No model output becomes canonical World State or Knowledge.
Provider failure cannot disable deterministic workflows or exact Knowledge lookup.
