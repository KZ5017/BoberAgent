# ADR 0007: Asynchronous incoming Session lifecycle

- Status: Accepted for Milestone 14
- Date: 2026-09-21

## Context

An incoming TCP connection is created by an external peer after the Capability Run that opened a
listener has completed. Keeping that Run alive indefinitely would conflate execution with durable
runtime infrastructure. Socket and asyncio task objects also cannot cross the SDK/transport
boundary or survive a Node restart.

## Decision

The Execution Node owns a native asyncio `tcp_listener` Resource, its accept tasks, and all live
stream handles. `network.listener/open` binds an explicit, scoped IP address and returns a durable
Resource descriptor immediately. An authorized accepted connection creates a separate durable
`tcp_stream` Session owned by the Listener's Mission provenance.

Core learns about the Session through a normalized `session.created` Event in the existing Node
Event outbox. The Event is correlated to the original listener-opening `CapabilityRunRef` because
the neutral transport's Event envelope already uses Run correlation; its payload carries the
stable Resource and Session refs. No listener-specific transport or MCP surface is added.

Capability code accesses a stream only through the SDK's generic `ByteStreamSession` protocol.
Reads and writes are exclusive, timeout bounded, and limited to 64 KiB. Result bytes use canonical
base64. Stream content is not persisted, logged, emitted in Events, interpreted as commands, or
automatically converted into Artifacts.

Wildcard binds are rejected. Allowed peer IPs and simultaneous Session capacity are explicit and
bounded. Closing a Listener closes all live child Sessions. On Node restart, non-terminal listener
Resources and stream Sessions become `LOST`; the Node never silently rebinds or claims TCP state
survived.

## Consequences

- Capability Runs remain finite while Resources and Sessions can outlive them.
- Core and transport observe only logical descriptors and Events, never sockets or asyncio tasks.
- Existing generic Resource/Session tables and lifecycle enums are sufficient; M14 needs no schema
  or Contract version change.
- Event-triggered workflow continuation, stream framing, TLS, UDP, shell semantics, PTYs, payload
  generation, and restart restoration remain deferred.
