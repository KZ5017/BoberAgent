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

Scope/entity data for the local test harness must be supplied explicitly. Secret resolution fails
closed unless Core included an explicit Mission-checked grant for this Run. Granted bytes remain
in the Execution Context lifetime and are not written to Node persistence; capability-side Secret
creation remains unavailable until a durable Core delivery path exists. Resolved UTF-8 values are
registered with the Run-local structured logger and redacted from subsequent messages/fields.
Managed process arguments are never logged or persisted, while raw tool output and Artifacts remain
unaltered evidence. Human Interaction uses the generic SDK interface and a Node-owned durable
request runtime: request persistence and `WAITING_INPUT` precede its outbox Event; a validated
response returns the Run to `RUNNING` and releases only the matching live waiter. Browser and TCP
listener providers are selected behind the generic SDK Resource/Session interfaces; unsupported
types fail explicitly.
`ExecutionPlan` execution is deliberately unavailable. Capability implementations must use
`boberagent_sdk` and must not import this package's persistence or manager internals.

The runtime finalizes `InteractionRequest.requested_at` at this durable activation boundary. A
timestamp supplied while capability code prepares the immutable request is not authoritative;
Node persistence, the request Event, Core projection, and CLI output all retain the finalized
activation timestamp unchanged.

Interaction request and response data survive an ordinary Core restart. A Node restart cannot
restore the suspended Python continuation: recovery cancels the durable request, fails the Run
with an unknown interrupted outcome, emits safe cancellation metadata, and rejects late answers.
Graceful shutdown releases waiters through typed cancellation so terminal state is persisted.

## MCP listener

`boberagent-node-mcp` starts the real Streamable HTTP carrier around an initialized Node. It binds
to loopback by default, reads its bearer credential from `BOBERAGENT_MCP_TOKEN` (or an explicitly
named environment variable), and accepts explicit capability paths and logical tool mappings.
Non-loopback plaintext binding is rejected unless the development override is deliberately set;
TLS certificate and key paths are supported. Stopping or reconnecting a client does not clear the
Node database, Artifact spool, or pending outboxes.
Pass a deliberate non-empty `--runtime-directory` (absolute paths are recommended for
operators). An empty or whitespace-only value is rejected before runtime initialization;
non-empty relative paths retain their existing behavior. Reuse the same directory across
ordinary restarts to preserve Node identity and local import/outbox state.

## M20-E4 preparation-owned source materialization

After authenticated E3 import, Core can explicitly request E4 CHECK or MATERIALIZE for the
same admitted `runtime.prepare` Run. CHECK re-verifies both exact imported Artifacts and
runs a fresh closed Linux bubblewrap probe without creating a workspace. MATERIALIZE creates
only a generated preparation-owned source area under
`<workspace-root>/preparation-source/{staging,published,quarantine}`. The Node persists
INCOMPLETE/VERIFIED/PUBLISHED/QUARANTINED state in migration
`0007_preparation_materialization`; it never publishes a partial tree. Reuse re-hashes every
file, and restart quarantines incomplete state. Physical paths are private to the Node.

The probe does not bind host `/`, `/etc`, `/home` or `/run`; it mounts only trusted `/usr`
and library directories read-only, minimal device/proc views and one managed writable
directory. It verifies a new network namespace against a controlled host listener. It
reports only E4 properties actually tested. E5 still needs hard process-count, memory,
storage and descendant enforcement before any preparation subprocess can be ready.
E4 creates no venv/Resource, imports or executes no acquired source, and grants no
execution authorization. Real Kali E4 CHECK, bounded materialization and same-runtime
restart/revalidation acceptance passed; E5 runtime preparation remains unimplemented.

## E5-C full-confinement foundation

`preparation.runtime_confinement` implements the separate closed Linux probe backend
`m20-e5-linux-bwrap-cgroup@1`. Explicit operator configuration supplies delegated cgroup parent
and Tool Registry-selected SHA-pinned static helper/bubblewrap. There is no automatic host
provisioning or active startup probe. Startup safety-reconciles only recorded owned operations.
Migration `0009_runtime_confinement` adds probe ownership/history/evidence; E5-B Resource
ownership, budget ledger, immutable pins and READY prohibition remain intact.

Supervisor/guardian, race-free cgroup attachment, namespaces, byte/inode-capped tmpfs, bounded
pipe drain and finite deadlines are detailed in [E5-C implementation](../../docs/m20/M20E5C_IMPLEMENTATION.md).
Closed probes do not inspect Python, build an environment or run acquired code. Only synthetic
source is mounted read-only. E5-C is **CLOSED** on operator real thirteen-probe Kali acceptance;
portable mocks/negative tests alone cannot close it. See the [operator-only command](../../scripts/manual-smoke/README.md#m20-e5-c-confinement-only-kali-preflight).
No new Core/SDK/MCP preparation endpoint or execution authority is added.

## E5-D trusted interpreter provenance

`PythonDistributionConfiguration` selects an explicit operator-preprovisioned uv CPython
3.12 Linux/x86_64 root and explicit system-library root with reviewed full-manifest/binary
pins. Production never invokes uv or discovers/downloads/installs/falls back to another
interpreter. Full filesystem trust/inventory precedes the separate fixed confined identity.
Migration `0010_python_provenance` retains immutable evidence on existing E5-B Resource
operations; READY guards are unchanged. Revalidation fully rehashes; historic proof grants
no fresh authority. See [implementation](../../docs/m20/M20E5D_IMPLEMENTATION.md) and the
[manual-only preflight](../../scripts/manual-smoke/README.md#m20-e5-d-trusted-cpython-provenance-only-kali-preflight).
**Implemented offline; real provenance acceptance required.** No venv, source execution,
transport endpoint or READY runtime exists. E5-E–H and M20-F remain untouched.
