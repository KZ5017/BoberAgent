# ADR 0001: Shared transport-neutral package

- Status: Accepted for Milestone 5
- Date: 2026-09-17

## Context

Core and Execution Node need a replaceable protocol boundary without either package importing the
other implementation. Contracts and the SDK must also remain free of transport infrastructure.

## Decision

Add `boberagent-transport`, depending only on `boberagent-contracts` and Pydantic. It owns protocol
versions, serialized envelopes, structural transport/endpoint interfaces, transport errors, and the
bounded in-memory adapter. Core owns its durable receiving inbox and client facade. Execution Node
owns its endpoint adapter and existing durable outboxes.

The package contains no Core orchestration, Node runtime behavior, networking, MCP, Artifact byte
transfer, or domain result ingestion.

## Consequences

Core and Execution Node both depend inward on the neutral protocol package while remaining
independent of each other. A future MCP adapter can replace the in-memory adapter without changing
Capability Contract objects, SDK APIs, capability implementations, World State, or the Node
Capability Runtime.
