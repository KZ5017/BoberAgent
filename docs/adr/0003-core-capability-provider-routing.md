# ADR 0003: Core provider identity and bootstrap routing policy

- Status: Accepted for Milestone 8
- Date: 2026-09-17

## Context

Execution Nodes advertise stable Capability definitions and Node-local availability. Core needs a
durable provider registry and deterministic routing without importing implementations, duplicating
dependency resolution, or assuming that persisted connectivity survives a Core restart.

## Decision

Core identifies a provider by a deterministic UUID5 derived from `(node_id, capability_id)`.
Implementation version is mutable provider metadata, not provider or Capability identity. Current
definitions, reported availability, Node health, first registration, last-seen time, and an
unavailability reason are persisted. A fresh Core Registry marks persisted providers `STALE` until
the Node performs another handshake; an injectable five-minute TTL also bounds live eligibility.

`READY` Nodes are routable. `DEGRADED` Nodes are routable only for providers that individually
advertise `AVAILABLE`; provider-level `DEGRADED` is excluded conservatively. Nodes that are
starting, draining, offline, failed, or missing a ready runtime database are ineligible.

Router v1 selects the lexicographically smallest stable provider UUID among eligible providers.
Explicit provider or Node constraints never fall back elsewhere. The selection and implementation
version are persisted per `CapabilityRunRef` before the existing transport submission is attempted;
transport failure does not trigger hidden rerouting.

## Consequences

Version refreshes do not accumulate duplicate providers, removed advertisements remain as
unavailable history, and Core restart never treats an old registration as live. Routing is
technical and deterministic rather than a quality score, workflow decision, or load-balancing
policy. Future transports can reuse the same Registry and Router through the neutral transport
interfaces.
