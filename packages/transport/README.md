# BoberAgent Transport

This package owns transport-neutral protocol envelopes, interfaces, errors, and the bounded
in-memory Milestone 5 adapter. It depends only on the Contract package and Pydantic. It contains no
Core business logic, Execution Node runtime logic, MCP types, networking, or Artifact transfer.

Protocol version `1.0` is independent from the Capability Contract version. Invocation, Event, and
Result payloads are composed from authoritative Contract objects and always cross a JSON
serialization/validation boundary.

The in-memory adapter uses bounded async queues. Submission is asynchronous from execution and
outbound delivery. When a queue is full, the operation fails explicitly with backpressure rather
than growing memory without bound. Disconnect stops new transport operations but does not cancel
Node work already accepted. Reconnect allows pending Node outboxes to be pumped again.

Events and Results remain pending until an explicit acknowledgement reaches the Node endpoint.
Lost acknowledgements therefore cause safe redelivery. The Core receiver is responsible for
deduplicating stable message IDs. Ordering is limited to each Node outbox's local sequence; there is
no global ordering guarantee across Nodes or unrelated Runs.
