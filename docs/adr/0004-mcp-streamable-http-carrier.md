# ADR 0004: MCP Streamable HTTP carrier

- Status: Accepted
- Date: 2026-09-18

## Context

BoberAgent already has a transport-neutral protocol, durable Execution Node Event/Result outboxes,
and a Core receiver. Milestone 10 requires a real network boundary without allowing MCP concepts to
become Contract or World State concepts. The MCP client/server direction also has to fit Node-owned
outboxes and Node-originated Artifact bytes.

## Decision

Add `boberagent-transport-mcp` as an infrastructure adapter above `boberagent-transport`. It may
depend on the official MCP Python SDK, but it must not import Core or Execution Node implementation
packages. Core-side and Node-side packages contain only narrow composition adapters.

Core is the MCP client and each Execution Node is an MCP Streamable HTTP server. BoberAgent's
protocol version, stable message identities, JSON envelopes, acknowledgements, and deduplication
remain authoritative. MCP tools are namespaced and generic; they do not expose capability-specific
tools, shell execution, arbitrary files, secrets, or databases.

Outbound delivery uses Core polling. Event and Result payloads are read from the existing Node
outboxes and acknowledged explicitly. Artifact synchronization is also Core-pulled: Core requests
bounded Node chunks, then feeds the existing transport-neutral start/chunk/finalize messages into
the existing Core Artifact receiver. This preserves persistence ownership and avoids a Core MCP
server solely for reverse delivery.

The server uses bearer authentication through the SDK authorization hook. Loopback is the default.
Remote plaintext endpoints require an explicit unsafe development override; normal remote
deployment requires TLS. Credentials are external configuration and are redacted by their model.

## Consequences

- `InMemoryTransport` remains available and transport-neutral domain/application services do not
  change for MCP.
- Disconnect does not cancel accepted Node work or clear outboxes/spool state; reconnect resumes
  polling and at-least-once delivery.
- There is no server-initiated push. Polling latency and scheduling remain application concerns.
- MCP discovery is not the Core Capability Registry, and MCP does not own Artifact or Result
  persistence.
- Cancellation, advanced authentication/authorization, scheduling, and workflow behavior remain
  future work.
