# BoberAgent Execution Node

This package implements the Milestone 4 local runtime foundation. It owns execution mechanics;
it does not own Mission state, World State, workflow strategy, or any Core persistence.

## Local runtime

`NodeConfiguration.for_runtime_directory(...)` derives an isolated runtime layout:

```text
runtime/
├── node-identity.json
├── runtime.sqlite3
├── workspaces/
├── process-output/
└── artifacts/
```

The generated `NodeId` is independent of process ID and hostname and is reused on restart. A
configured ID may be supplied on first initialization; later mismatches fail safely.
`ExecutionNode.initialize()` migrates the Node-owned SQLite database, recovers interrupted local
records, discovers capability manifests, inspects configured tools, and transitions from
`STARTING` to `READY` or `DEGRADED`. `health()` remains local runtime state.

The database is migration-driven through Alembic. Startup applies revisions rather than recreating
tables. Tests always use temporary runtime directories. The schema records local Runs, managed
processes and workspaces, Artifact spool metadata, pending Event/Result outboxes, and safe logical
Resource/Session metadata; it is not a World State database. Browser cookies, local storage,
credentials, Playwright objects, and other live browser state are never written to this database.

## Capabilities and tools

Capability discovery scans configured paths for static `capability.json` manifests. Each manifest
contains an authoritative `CapabilityDefinition` plus lazy Python entry points for the Capability
class and operation input models. Metadata is validated without importing implementation modules.
Duplicate IDs and malformed manifests are reported independently so one broken provider does not
hide unrelated providers.

The transport handshake advertises each discovered definition together with its Node-local
`AVAILABLE`, `DEGRADED`, or `UNAVAILABLE` status and a bounded reason where applicable. The Node
does not select among providers or implement Core routing policy.

Tools are registered by logical name and resolved from an explicit executable hint or `PATH`.
Optional version probes feed dependency checks; the Node detects missing requirements but never
installs them. Capability code still sees only the SDK `ProcessService`, not registry paths.

## Managed execution and storage

Known tools run with asyncio argument-vector APIs and never through `shell=True`. The service uses
an explicit minimal environment, tracks Run ownership/PID/timestamps, supports timeout and
cooperative cancellation, and captures stdout/stderr to managed files. Small output is returned
inline; output above the configured bound is moved into the Artifact spool and returned by
`ArtifactRef`.

Workspaces have logical IDs, persistent ownership metadata, and generated paths constrained below
the configured root. Artifact IDs are UUID-based logical references; spool metadata includes hash,
size, producing Run, local path, and synchronization state. New Artifacts remain `LOCAL_ONLY`;
the explicit synchronization coordinator or MCP pull adapter advances them only after Core's
durable integrity-checked acknowledgement.

Capability Events and terminal Results are persisted before delivery. The transport-neutral
`ExecutionNodeTransportEndpoint` validates serialized neutral protocol envelopes, delegates only
to `CapabilityRuntime`, and exposes those existing outboxes. Stable Event IDs and the unique
Run/result key make delivery idempotent; records become delivered only after acknowledgement.
Transport disconnect does not cancel accepted Node work.

`ArtifactSyncCoordinator` explicitly pumps `LOCAL_ONLY`, `SYNC_PENDING`, and retryable
`SYNC_FAILED` spool entries over the neutral transport. It streams confined spool files in bounded
chunks, persists attempt time/count and the latest diagnostic, and marks `SYNCED` only after Core's
durable acknowledgement. Local bytes are retained after synchronization and across restart.

## Browser Resources and Sessions

The first concrete Resource/Session provider is an explicitly provisioned headless Chromium
runtime behind Playwright. `browser.interaction` asks the SDK to create a `browser_process`
Resource and a distinct `browser` Session. The Node resolves the logical `chromium` dependency
through its Tool Registry; it never downloads a browser during invocation. Capability code sees
only the SDK's semantic `BrowserSession` driver, not Playwright objects.

M13 deliberately uses one browser Resource per Session. The Resource owns the browser process;
the Session owns its context/page, cookies, local storage, and navigation state. Both receive
stable logical references and durable lifecycle records. Access is exclusive, navigation is
limited to normalized HTTP(S) hosts authorized by the invocation projection, and Playwright route
interception blocks redirects and subrequests that leave that host policy. HTML inspection is
bounded and leaves the Node through the ordinary Artifact spool.

Resource states are `CREATING`, `READY`, `FAILED`, `CLOSING`, `CLOSED`, and `LOST`; Session states
are `CREATING`, `ACTIVE`, `FAILED`, `CLOSING`, `CLOSED`, and `LOST`. Closing a Session or Resource
is idempotent, and Resource close first closes dependent Sessions. Graceful Node shutdown closes
live browser runtimes. After an unclean restart, non-terminal browser Resources and Sessions are
marked `LOST`: durable identity survives, but sensitive in-memory browser state is never fabricated
or silently restored.

## TCP Listener Resources and incoming Sessions

`network.listener` creates a Node-owned `tcp_listener` Resource. The capability returns as soon as
the explicitly scoped address/port is bound; it does not hold a Capability Run open while waiting
for a peer. Native asyncio accept handling remains in the Execution Node. Each authorized incoming
connection creates a durable `tcp_stream` Session with a stable `SessionRef`, then emits a
`session.created` Event through the existing persistent Event outbox. No listener-specific
transport or MCP operation exists.

The bind address and every allowed peer address must be explicit IP literals present in the
invocation scope. Wildcard binds are rejected. Each listener has a bounded simultaneous-Session
capacity (maximum 32); excess or unauthorized connections are closed and produce metadata-only
`session.rejected` Events. The semantic SDK driver permits exclusive, timeout-bounded reads and
writes of at most 64 KiB. Stream bytes are never logged, persisted in runtime tables, emitted as
Events, or automatically stored as Artifacts.

One Listener can own multiple distinct incoming Sessions. Closing one Session leaves its Listener
ready. Closing the Listener stops acceptance, closes all dependent live Sessions, and waits for
its Node-owned tasks and sockets. Listener and stream handles are not restart-restorable, so Node
startup marks surviving non-terminal `tcp_listener` and `tcp_stream` records `LOST`; it never
silently rebinds an endpoint.

## Recovery policy

Completed Runs are replayed from the Result outbox when the same `CapabilityRunRef` is submitted
again. On restart, a locally `RUNNING`/`QUEUED` Run that cannot be proven complete is marked failed
with an unknown interrupted outcome; its process records become `LOST`. The Node never blindly
re-executes potentially state-changing work. Artifacts, workspaces, and pending outbox records are
retained.

Scope/entity data for the local test harness must be supplied explicitly. Services requiring Core
(Secrets and Interactions) fail closed. Browser and TCP listener providers are selected behind the
generic SDK Resource/Session interfaces; unsupported types fail explicitly.
`ExecutionPlan` execution is deliberately unavailable. Capability implementations must use
`boberagent_sdk` and must not import this package's persistence or manager internals.

## MCP listener

`boberagent-node-mcp` starts the real Streamable HTTP carrier around an initialized Node. It binds
to loopback by default, reads its bearer credential from `BOBERAGENT_MCP_TOKEN` (or an explicitly
named environment variable), and accepts explicit capability paths and logical tool mappings.
Non-loopback plaintext binding is rejected unless the development override is deliberately set;
TLS certificate and key paths are supported. Stopping or reconnecting a client does not clear the
Node database, Artifact spool, or pending outboxes.
