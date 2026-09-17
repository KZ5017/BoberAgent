# BoberAgent Transport

This package owns transport-neutral protocol envelopes, interfaces, errors, and the bounded
in-memory Milestone 5 adapter. It depends only on the Contract package and Pydantic. It contains no
Core business logic, Execution Node runtime logic, MCP types, networking, or Artifact storage.

Protocol version `1.2` is independent from the Capability Contract version. Invocation, Event,
Result, and dedicated Artifact-transfer messages always cross a JSON serialization/validation
boundary. Artifact bytes use bounded base64-encoded chunks with explicit offsets and per-chunk
SHA-256; they are never embedded in Results or Events.

The Node handshake composes validated `CapabilityDefinition` objects with a small per-capability
availability projection. This is discovery metadata only: Core owns registry persistence and
routing policy, while each Node remains authoritative for its local dependency checks.

The in-memory adapter uses bounded async queues. Submission is asynchronous from execution and
outbound delivery. When a queue is full, the operation fails explicitly with backpressure rather
than growing memory without bound. Disconnect stops new transport operations but does not cancel
Node work already accepted. Reconnect allows pending Node outboxes to be pumped again.

Events and Results remain pending until an explicit acknowledgement reaches the Node endpoint.
Lost acknowledgements therefore cause safe redelivery. The Core receiver is responsible for
deduplicating stable message IDs. Ordering is limited to each Node outbox's local sequence; there is
no global ordering guarantee across Nodes or unrelated Runs.

Artifact synchronization is a separate request/response stream: start, ordered chunks, finalize,
then durable acknowledgement or structured rejection. The adapter moves serialized messages only;
the Node owns source bytes and retry state, while Core owns temporary files, integrity verification,
and canonical storage.
