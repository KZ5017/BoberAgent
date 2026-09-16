# BoberAgent Core — Execution Node v1

**Status:** Initial normative specification
**Document:** `docs/07_EXECUTION_NODE.md`
**Related:** `01_SYSTEM_ARCHITECTURE.md`, `02_CAPABILITY_CONTRACT.md`, `03_CAPABILITY_SDK.md`, `04_WORLD_STATE_MODEL.md`, `05_WORKFLOW_AND_REASONING.md`

---

# 1. Purpose

This document defines the BoberAgent Execution Node architecture.

The Execution Node is responsible for executing Capabilities in a controlled environment.

The initial Execution Node runs inside the Kali Linux Hyper-V VM.

It owns runtime mechanisms such as:

* tool execution;
* capability loading;
* long-running processes;
* browsers;
* listeners;
* runtime environments;
* workspaces;
* live Sessions;
* local cancellation;
* local dependency resolution;
* temporary Artifact spooling;
* local policy enforcement.

The Execution Node is not the BoberAgent Core.

---

# 2. Core Principle

The Execution Node answers:

> How is an approved Capability operation actually executed?

The Core answers:

> Why should it execute, what does it mean, and what should happen next?

The boundary MUST remain explicit.

---

# 3. Initial Deployment

```text
Windows Host
│
│
├── BoberAgent Core
│
│    Mission / Workflow / World State / Policy / Knowledge / LLM
│
└─────────────── transport ─────────────────┐
                                            │
                                            ▼
                                   Kali Hyper-V VM
                                            │
                                  BoberAgent Execution Node
                                            │
                 ┌──────────────────────────┼─────────────────────┐
                 │                          │                     │
          Capability Runtime         Runtime Managers       Tooling
                 │                          │                     │
          Capability Plugins      Process / Resource         nmap
                                  Session / Workspace        nxc
                                  Artifact / Secret          git
                                                           Playwright
                                                           hashcat
                                                           etc.
```

The architecture MUST permit additional Execution Nodes later.

---

# 4. Execution Node Is a Platform Component

The Execution Node MUST NOT be implemented as merely:

```text
an MCP server exposing shell commands
```

It is a managed runtime with its own domain responsibilities.

MCP or another transport is only an external interface.

---

# 5. Major Components

Execution Node v1 contains:

```text
Node Identity / Health

Transport Adapter

Capability Registry
Capability Runtime

Dependency Resolver
Tool Registry

Process Manager
Resource Manager
Session Manager
Workspace Manager

Artifact Client / Local Spool
Secret Resolver

Interaction Continuation Support
Checkpoint Store

Local Policy Enforcement
Audit / Logging

Runtime Persistence
Recovery Manager
```

---

# 6. Authority Boundary

The following remain authoritative in BoberAgent Core:

```text
Mission
Scope definition
World State
Observation Store
Workflow state
Goal state
Procedure Registry
global Capability Registry
Policy configuration
Secret Store
Artifact Catalog
Knowledge
Reasoning
```

The Execution Node MUST NOT become an alternative authority for these concepts.

---

# 7. Node-Owned Runtime State

The Execution Node is authoritative for the live runtime state of objects it hosts.

Examples:

```text
PID of managed process
live Playwright browser object
listener socket
SSH connection
reverse-shell transport
temporary workspace path
Python virtual environment path
lease ownership
local process status
```

Core stores logical metadata and handles.

The node owns the actual live implementation object.

---

# 8. Stable Node Identity

Every Execution Node MUST have a stable:

```text
node_id
```

Example:

```text
node-kali-01
```

The identity MUST survive ordinary process restarts.

It MUST NOT depend on:

```text
current PID
temporary IP address
process start time
```

---

# 9. Node Metadata

The node SHOULD advertise metadata including:

```text
node_id
node version
platform
OS
architecture
runtime version
supported contract versions
supported SDK versions
capabilities
tool inventory summary
health state
```

Sensitive host details SHOULD only be exposed where operationally useful.

---

# 10. Node Lifecycle

Logical node state SHOULD support:

```text
STARTING
READY
DEGRADED
DRAINING
OFFLINE
FAILED
```

`DEGRADED` means the node remains usable but some expected functionality is unavailable.

Example:

```text
Playwright unavailable
but Nmap capabilities still usable.
```

---

# 11. Node Startup

Startup SHOULD perform:

```text
load configuration
establish node identity
open runtime database
recover persisted runtime records
discover capabilities
validate manifests
inspect tool dependencies
start runtime managers
reconcile surviving Resources
start transport endpoint
advertise node state
```

The node SHOULD NOT advertise `READY` before critical bootstrap validation succeeds.

---

# 12. Transport Boundary

Transport carries structured platform messages such as:

```text
capability discovery
CapabilityInvocation
CapabilityRun control
cancellation
events
result delivery
Resource/Session status
health
interaction continuation
```

Transport MUST NOT define Capability semantics.

---

# 13. Initial Transport

MCP MAY be the initial Core ↔ Execution Node transport.

Transport-specific code MUST remain under:

```text
execution_node/transport/
```

Core Capability and domain packages MUST NOT import MCP-specific types.

---

# 14. Transport Adapter

Conceptually:

```text
Core domain object
      ↓
Capability Transport abstraction
      ↓
MCP adapter
      ↓
network
      ↓
MCP adapter
      ↓
Execution Node domain object
```

A future transport SHOULD be replaceable without rewriting Capability implementations.

---

# 15. Connection Model

Core and Execution Node MUST tolerate temporary connection loss.

Connection loss does NOT automatically mean:

```text
all running capabilities failed
all sessions disappeared
all resources stopped
```

Live node-side work MAY continue depending on operation semantics.

---

# 16. Heartbeat

The Execution Node SHOULD provide periodic heartbeat/status information.

Heartbeat MAY include:

```text
node state
node uptime
active CapabilityRun count
active Resource count
active Session count
queued work
local storage pressure
dependency health summary
```

Heartbeats MUST NOT contain secrets.

---

# 17. Disconnect Detection

Core SHOULD mark a node temporarily unavailable when heartbeat or transport communication is lost.

Node-hosted objects SHOULD initially transition conceptually to:

```text
UNKNOWN / UNREACHABLE
```

rather than immediately:

```text
CLOSED / FAILED
```

until reconciliation determines their actual state.

---

# 18. Reconnection

After reconnect, Core and Execution Node MUST reconcile:

```text
active CapabilityRuns
Resources
Sessions
pending results
pending events
pending Artifacts
interaction waits
```

The node MUST have sufficient durable runtime metadata to perform this reconciliation.

---

# 19. Capability Registry

The local Capability Registry discovers Capability packages installed on the node.

It MUST read CapabilityDefinition metadata without executing implementation code.

Discovery flow:

```text
capability package discovered
        ↓
manifest parsed
        ↓
schema validated
        ↓
contract compatibility checked
        ↓
dependencies evaluated
        ↓
implementation entry point recorded
        ↓
capability advertised
```

---

# 20. Invalid Capability Package

An invalid capability MUST NOT become executable.

The node SHOULD record diagnostics such as:

```text
INVALID_MANIFEST
UNSUPPORTED_CONTRACT_VERSION
INVALID_SCHEMA
MISSING_IMPLEMENTATION
UNRESOLVED_DEPENDENCY
```

One broken plugin MUST NOT prevent unrelated valid capabilities from loading.

---

# 21. Capability Availability

Capability availability SHOULD distinguish:

```text
AVAILABLE
DEGRADED
UNAVAILABLE
DISABLED
```

Example:

```text
credential.validation
implementation installed

but nxc unavailable

→ UNAVAILABLE
```

---

# 22. Tool Registry

The Tool Registry represents executable tools known to the node.

Example entries:

```text
nmap
nxc
git
python
hashcat
john
ffuf
```

Tool identity MUST be separate from Capability identity.

---

# 23. Tool Record

Tool metadata SHOULD include:

```text
tool ID
resolved executable path
detected version
health
supported implementations
last validation timestamp
```

Absolute executable paths remain node-local implementation details.

---

# 24. Tool Discovery

Tool discovery MAY use:

```text
configured locations
PATH lookup
version probes
provider-specific discovery
```

A Capability SHOULD request:

```text
tool="nmap"
```

rather than hard-code:

```text
/usr/bin/nmap
```

where possible.

---

# 25. Dependency Resolver

Before capability execution, the node MUST validate declared runtime dependencies.

Dependencies MAY include:

```text
tool
tool version
Python/runtime version
Resource provider
Session driver
local library
other node capability
```

Dependency failure MUST occur before unsafe partial execution where possible.

---

# 26. Capability Runtime

The Capability Runtime owns one CapabilityRun's node-side execution lifecycle.

Conceptual flow:

```text
receive invocation
      ↓
validate contract
      ↓
validate operation input
      ↓
validate scope
      ↓
validate local policy
      ↓
resolve dependencies
      ↓
construct ExecutionContext
      ↓
load implementation
      ↓
execute
      ↓
validate CapabilityResult
      ↓
persist delivery state
      ↓
send result
```

---

# 27. Run Identity

Core creates the canonical:

```text
run_id
```

The node MUST execute under that identity.

A retry that represents a new CapabilityRun MUST receive a new run ID.

The node MUST NOT silently create replacement Runs that Core does not know about.

---

# 28. Duplicate Invocation Protection

Receiving the same `run_id` more than once MUST NOT cause accidental duplicate execution.

The node MUST check its local Run registry.

Possible behavior:

```text
run already running
→ return current state

run already completed
→ replay stored terminal result

run unknown
→ start execution
```

This is important during reconnect/retry.

---

# 29. Runtime Persistence

Execution Node v1 SHOULD use a small local SQLite database for runtime metadata.

This database is NOT World State.

It MAY store:

```text
node configuration identity
CapabilityRun execution metadata
Resource records
Session records
leases
Workspace records
Artifact spool metadata
pending events/results
checkpoints
```

---

# 30. Runtime Database Purpose

The node database exists primarily for:

```text
crash recovery
reconnect reconciliation
duplicate invocation protection
runtime ownership
durable wait/resume
```

It MUST NOT become a shadow copy of the entire Core database.

---

# 31. Process Manager

All managed external processes SHOULD run through Process Manager.

Capability implementations SHOULD NOT launch unmanaged subprocesses.

Process Manager owns:

```text
process creation
environment
stdin/stdout/stderr
timeout
cancellation
exit status
ownership
logging
Artifact capture
```

---

# 32. Managed Process

A managed process MUST have a logical process record.

Example:

```yaml
process_id: process-91
run_ref: run-17

tool: nmap
state: RUNNING

pid: 4182

started_at: ...
```

PID is runtime metadata, not public identity.

---

# 33. Process Lifecycle

Suggested states:

```text
CREATED
STARTING
RUNNING
EXITED
CANCELLED
TIMED_OUT
FAILED
LOST
```

---

# 34. Standard Output Handling

Process stdout and stderr SHOULD support:

```text
bounded live streaming
durable capture
Artifact creation
```

Large output MUST NOT be retained solely in memory.

---

# 35. Output Size Control

The Process Manager SHOULD support:

```text
stream buffer limits
Artifact spill-to-disk
maximum inline event size
```

The Core SHOULD receive references for large outputs rather than enormous event payloads.

---

# 36. Environment Construction

The Process Manager SHOULD construct explicit process environments.

It SHOULD avoid blindly inheriting the entire Execution Node service environment.

This reduces accidental secret leakage and improves reproducibility.

---

# 37. Secret Injection

Sensitive process input MAY be injected through approved mechanisms such as:

```text
stdin
ephemeral protected file
restricted environment variable
tool-specific secure channel
```

Command-line arguments SHOULD be avoided for secrets where practical.

---

# 38. Secret Redaction

Process logging MUST support known-secret redaction.

The platform MUST assume that third-party tools may accidentally echo supplied secrets.

Captured raw evidence containing secrets MAY require restricted Artifact classification.

---

# 39. Known Tool Execution

Known tools execute through registered Tool definitions.

Conceptually:

```text
ctx.processes.run_tool("nmap", ...)
```

The Process Manager resolves:

```text
tool ID
→ executable
→ validated version
→ execution policy
```

---

# 40. Arbitrary Code Execution

Unknown acquired PoC code MUST use the ExecutionPlan path.

Conceptually:

```text
Artifact
      ↓
ExecutionPlan
      ↓
validation
      ↓
runtime preparation
      ↓
managed process
```

Unknown code MUST NOT receive unrestricted node-level execution merely because an LLM requested it.

---

# 41. Runtime Isolation Classes

Execution Node SHOULD define runtime isolation profiles.

Initial examples:

```text
HOST_MANAGED
WORKSPACE_ISOLATED
PYTHON_VENV
CONTAINER
```

Not every capability requires a container.

Isolation SHOULD be proportional to the operation.

---

# 42. Unknown PoC Default

Unknown third-party executable code SHOULD default to stronger isolation than trusted built-in capability code.

Where supported, prefer:

```text
dedicated Workspace
isolated dependency environment
explicit network requirements
explicit file bindings
managed process
```

Container isolation MAY be added when appropriate.

---

# 43. Workspace Manager

Workspace Manager owns filesystem areas used by CapabilityRuns and Resources.

Typical structure MAY resemble:

```text
runtime/
└── workspaces/
    ├── run-...
    ├── resource-...
    └── mission-...
```

Physical paths MUST remain node-local details.

---

# 44. Workspace Scope

Supported workspace scopes SHOULD include:

```text
RUN
RESOURCE
MISSION
```

`RUN` is the preferred default.

Long-lived Resources may require Resource-scoped workspaces.

---

# 45. Workspace Lifecycle

Workspaces SHOULD support:

```text
CREATED
ACTIVE
RETAINED
CLEANUP_PENDING
REMOVED
```

Retention MAY depend on:

```text
debug requirement
Artifact capture completion
active Resource ownership
Mission policy
```

---

# 46. Workspace Security

Capabilities MUST NOT receive unrestricted filesystem access through the SDK.

Workspace paths define the normal writable boundary.

Built-in trusted implementations MAY require additional explicitly configured access.

Such access MUST be declared and auditable.

---

# 47. Artifact Client

The Execution Node needs Artifact access even when the Core connection is temporarily unavailable.

Therefore the node SHOULD use:

```text
Artifact Client
+
durable local Artifact spool
```

---

# 48. Artifact Creation

When a capability calls:

```text
ctx.artifacts.create(...)
```

the node:

```text
assigns globally unique logical Artifact ID
      ↓
stores bytes in local spool
      ↓
computes metadata/hash
      ↓
records provenance
      ↓
attempts synchronization with Core
```

The returned ArtifactRef is stable immediately.

---

# 49. Artifact Identity

Artifact IDs SHOULD use a globally unique identifier strategy.

Identity MUST NOT depend on successful immediate upload to Core.

This permits Capability execution to finish during temporary Core disconnection.

---

# 50. Artifact Synchronization

Artifact states MAY include:

```text
LOCAL_ONLY
SYNC_PENDING
SYNCED
SYNC_FAILED
```

A Run MAY produce a valid terminal result while some associated large Artifacts remain:

```text
SYNC_PENDING
```

The node MUST continue retrying delivery according to policy.

---

# 51. Artifact Loss Prevention

A locally unsynchronized Artifact MUST NOT be deleted during normal cleanup.

Workspace cleanup MUST account for Artifact-spool ownership.

---

# 52. Secret Resolver

Canonical secrets remain owned by the Core Secret Store.

The Execution Node SHOULD NOT maintain a general persistent replica.

When required:

```text
CapabilityRun
      ↓
authorized Secret resolution
      ↓
short-lived delivery to node
      ↓
runtime use
      ↓
memory/temporary material cleanup
```

---

# 53. Secret Cache

Persistent generic secret caching SHOULD be disabled by default.

A short-lived in-memory cache MAY exist for one Run where useful.

Any persistent secret material required by an active Resource MUST have explicit secure semantics.

---

# 54. Node Offline and Secrets

A capability requiring a secret that has not already been securely resolved MUST NOT invent or bypass authorization during Core disconnection.

It SHOULD enter an appropriate blocked/waiting state or fail according to operation semantics.

---

# 55. Resource Manager

Resource Manager owns live node-side infrastructure.

Examples:

```text
listener
browser process
Python environment
Burp project
container
tunnel
long-running service
```

Capabilities MUST interact with registered Resource providers.

---

# 56. Resource Provider

A Resource Provider implements one Resource type.

Conceptually:

```text
ListenerProvider
BrowserProvider
PythonEnvironmentProvider
BurpProvider
ContainerProvider
```

Provider interface SHOULD support:

```text
create
inspect
acquire
release
close
recover
```

where meaningful.

---

# 57. Resource Record

Node runtime metadata SHOULD contain:

```text
resource_id
resource_type
provider
owner
state
workspace_ref
runtime metadata
created_by_run
created_at
cleanup policy
```

Sensitive provider internals MUST NOT be exposed unnecessarily to Core.

---

# 58. Resource Lifetime

A Resource MAY outlive the CapabilityRun that created it.

Example:

```text
listener.start Run
      ↓
COMPLETED

Listener Resource
      ↓
remains READY for 30 minutes
```

This is a required architectural behavior.

---

# 59. Resource Ownership

Resource ownership MUST be explicit.

Possible owners:

```text
CapabilityRun
Workflow
Mission
```

A Resource promoted beyond Run lifetime SHOULD normally become Workflow- or Mission-owned.

---

# 60. Resource Lease

Concurrent access MUST use Resource leases.

Lease state MUST be persisted sufficiently to recover safely after runtime restart.

Expired stale leases SHOULD be reclaimable according to Resource type policy.

---

# 61. Resource Recovery

After Execution Node restart, each persisted Resource must be reconciled.

Possible results:

```text
RECOVERED
STILL_ACTIVE
STOPPED
LOST
FAILED
```

The runtime MUST NOT simply assume that all persisted Resources survived.

---

# 62. Recoverable Resources

Some Resources are naturally recoverable.

Example:

```text
Python virtual environment on disk
workspace
container managed by persistent container runtime
```

Others may not be:

```text
in-memory browser process
raw TCP listener owned by dead process
```

Recovery behavior is provider-specific.

---

# 63. Lost Resource

If a Resource cannot be recovered:

```text
Resource state → LOST/FAILED
      ↓
event sent to Core
      ↓
dependent Workflows reevaluate
```

Core MAY later decide to recreate it.

The Execution Node MUST NOT autonomously recreate semantically significant Resources unless contract/policy explicitly permits it.

---

# 64. Session Manager

Session Manager owns live interactive contexts.

Examples:

```text
SSH connection
WinRM connection
reverse shell
browser context
database connection
authenticated HTTP context
```

---

# 65. Session Driver

A SessionDriver hides provider-specific runtime mechanics.

Conceptually:

```text
Session
      ↓
SessionDriver
      ↓
SSH / WinRM / Playwright / Penelope / ...
```

Capabilities request abstract supported operations.

---

# 66. Session Capabilities

A Session MAY advertise operations such as:

```text
command_execute
file_upload
file_download
navigate
http_request
database_query
```

Capability applicability SHOULD depend on these semantic operations rather than the original acquisition mechanism.

---

# 67. Reverse Shell Example

```text
Listener Resource
      ↓
incoming connection
      ↓
Session Manager
      ↓
RemoteShellSession
      ↓
session.created event
      ↓
Core registers Session
      ↓
AccessContext establishment
```

The original listener-start CapabilityRun need not still be active.

---

# 68. Browser Example

```text
BrowserProcess Resource
      ↓
BrowserSession
      ↓
navigate / click / fill
      ↓
Session state remains alive
```

The actual Playwright objects stay inside the node runtime.

Core receives only logical Session/Resource state and relevant assessment evidence.

---

# 69. Session Lifetime

A Session MAY outlive:

```text
the CapabilityRun that created it
the transport request
the Workflow step that established it
```

It normally remains bounded by:

```text
Session state
Mission ownership
provider health
operator/policy cleanup
```

---

# 70. Session Health

Session Manager SHOULD support health checks appropriate to Session type.

State MAY include:

```text
CREATING
ACTIVE
DEGRADED
CLOSED
FAILED
LOST
```

Health checks SHOULD avoid unnecessary disruptive activity.

---

# 71. Session Disconnect

Unexpected connection loss SHOULD produce:

```text
session state update
event
diagnostic
```

It MUST NOT silently remove the Session record.

Historical Session metadata remains useful.

---

# 72. Session Recovery

After node restart:

* persistent/reconnectable Sessions MAY be recovered;
* non-recoverable Sessions MUST become `LOST`;
* Core MUST be notified.

A reverse shell whose process died with the node is normally not recoverable.

A durable SSH Session may potentially be re-established only if policy and semantics permit it.

Re-establishment MUST NOT silently impersonate survival of the original Session.

---

# 73. New Session on Reconnect

If a connection is deliberately re-established, it SHOULD normally create a new Session identity linked to the previous Session.

This preserves provenance.

---

# 74. Burp Runtime

Burp integration SHOULD be represented through Resource and Session primitives rather than special Core architecture.

Possible model:

```text
BurpProject Resource
BurpProxy Resource

Browser Session
      ↓
configured through proxy

captured traffic
      ↓
Artifact / Observation
```

Exact Burp control mechanism may evolve independently.

---

# 75. Listener Manager

Listeners SHOULD be Resource types.

A listener Resource SHOULD expose metadata such as:

```text
protocol
bind address
port
state
provider
created_by_run
expiration
```

Sensitive or unnecessary provider internals remain node-local.

---

# 76. Port Allocation

Where a listener needs a local port, Resource Manager SHOULD support managed allocation.

This avoids two concurrent capabilities accidentally binding the same port.

Port allocation SHOULD be lease-aware.

---

# 77. Callback Address

The system MUST distinguish:

```text
listener bind address
```

from:

```text
callback/reachable address presented to target
```

Network topology may make these different.

The provider/runtime SHOULD represent both explicitly where required.

---

# 78. Interaction Waiting

A CapabilityRun may enter:

```text
WAITING_INPUT
```

while its Resources remain active.

Example:

```text
PoC attempt failed
listener remains READY
Run requests human alternative payload
```

The runtime MUST preserve referenced Resources while the Checkpoint requires them.

---

# 79. Durable Interaction

Waiting for human input MUST NOT depend on one continuously alive transport call.

The node persists:

```text
Run state
Checkpoint
InteractionRequest reference
required Resource/Session references
```

The active implementation can later be reconstructed.

---

# 80. Checkpoint Store

Checkpoint data belongs to runtime persistence.

A Checkpoint MUST contain serializable logical state.

It MUST NOT contain live runtime objects.

Allowed:

```text
phase
ArtifactRef
ResourceRef
SessionRef
attempted values
next state
```

Not allowed:

```text
socket object
file descriptor
coroutine object
Playwright page object
```

---

# 81. Capability Continuation Model

Capability implementations with durable waits SHOULD behave as explicit state machines.

Conceptually:

```text
phase = INITIAL
      ↓
phase = TRY_KNOWN_VARIANTS
      ↓
phase = WAIT_FOR_INPUT
      ↓
phase = RETRY_CUSTOM
      ↓
phase = VERIFY
```

This is preferable to preserving a suspended Python stack indefinitely.

---

# 82. Node Scheduler

Core owns strategic scheduling.

Execution Node MAY have a local technical scheduler for:

```text
run queue
worker limits
CPU-heavy tasks
Resource limits
```

The node scheduler MUST NOT choose new assessment actions.

---

# 83. Resource Limits

The node SHOULD support configurable local limits for:

```text
concurrent CapabilityRuns
CPU-heavy processes
browser instances
hash cracking jobs
listeners
workspace storage
Artifact spool size
```

Exceeding a local limit SHOULD result in queueing or Resource-unavailable semantics, not uncontrolled resource exhaustion.

---

# 84. CPU/GPU Workloads

Local compute capabilities MAY require substantial CPU or GPU resources.

Capability metadata MAY later declare resource hints such as:

```text
CPU class
memory class
GPU required/preferred
```

v1 MAY implement only basic concurrency classes.

The contract SHOULD leave room for richer scheduling.

---

# 85. Local Policy Enforcement

The Execution Node MUST perform local enforcement for critical constraints.

At minimum:

```text
scope
operation authorization token/context
declared capability identity
restricted runtime operations
secret access
```

The node MUST NOT blindly trust arbitrary transport messages to execute shell commands.

---

# 86. Defense in Depth

Even if Core already approved an Invocation:

```text
Core policy check
      +
Execution Node validation
```

SHOULD both occur.

Execution Node enforcement protects against:

```text
transport bugs
stale requests
misrouting
compromised higher-level component
implementation errors
```

---

# 87. Scope Materialization

The node MAY receive a signed/validated scope projection relevant to the Run.

It MUST NOT require full Mission state merely to enforce target scope.

Dynamic targets discovered during execution MUST be validated before target-facing interaction.

---

# 88. Capability Permission Envelope

An Invocation SHOULD carry an execution permission envelope sufficient for node-side validation.

Conceptually:

```text
run_id
capability
operation
mission_ref
scope context
approved risk context
expiration
```

The exact cryptographic mechanism may be added later.

---

# 89. Audit Log

Execution Node SHOULD maintain structured audit logs for:

```text
Run start/end
managed process launch
secret resolution
Resource lifecycle
Session lifecycle
scope denial
policy denial
Artifact creation
runtime recovery
```

Logs MUST avoid unnecessary secret values.

---

# 90. Event Delivery

Node-generated Events SHOULD be persisted until acknowledged or safely reconciled with Core.

Temporary network failure MUST NOT silently discard:

```text
session.created
resource.failed
run.completed
```

events.

---

# 91. Event Identity

Every Event MUST have a globally unique ID.

Core event processing MUST tolerate duplicates.

This enables at-least-once delivery semantics.

---

# 92. Result Delivery

Terminal CapabilityResult MUST be persisted locally before final delivery acknowledgement.

If Core disconnects:

```text
Run completes
      ↓
Result stored locally
      ↓
delivery pending
      ↓
reconnect
      ↓
result replayed
```

The Capability MUST NOT execute again solely because acknowledgement was lost.

---

# 93. At-Least-Once Transport

Transport v1 MAY use at-least-once delivery.

Therefore the following MUST be idempotently handled:

```text
Invocation delivery
Event delivery
Result delivery
Artifact metadata synchronization
```

Exactly-once distributed execution is not required.

Duplicate suppression is required.

---

# 94. Crash During Capability Execution

After node restart, a previously `RUNNING` CapabilityRun must be reconciled.

Possible states:

```text
underlying managed process survived and can be reattached
underlying Resource survived
execution definitely terminated
execution status unknown
```

The runtime MUST NOT automatically mark every interrupted Run as safely retryable.

---

# 95. Unknown Crash Outcome

If it cannot determine whether a state-changing operation completed:

```text
execution result = UNKNOWN
diagnostic = INTERRUPTED_EXECUTION_STATE_UNKNOWN
```

This is especially important for PoCs and target-modifying operations.

Automatic retry MUST respect idempotency semantics.

---

# 96. Process Survival

Execution Node service process failure does not necessarily imply child-process death if the OS/provider allows independent supervision.

v1 MAY choose simpler parent-owned lifecycle semantics.

However, long-lived Resources SHOULD increasingly use provider supervision rather than accidental process parentage.

---

# 97. Node Shutdown

Graceful node shutdown SHOULD:

```text
stop accepting new Runs
enter DRAINING
persist runtime state
request cancellation or detach according to Resource policy
flush pending events/results
preserve Artifact spool
close transport
```

Mission-owned Resources MAY require explicit policy before termination.

---

# 98. Forced Shutdown

On forced shutdown, recovery logic must assume live runtime state may be uncertain.

Recovered Resources/Sessions MUST be inspected before being advertised as active.

---

# 99. Artifact Spool Pressure

The node MUST monitor local Artifact spool usage.

When storage pressure becomes dangerous:

```text
node → DEGRADED
new large-output Runs may be rejected
Core notified
```

Unsynchronized evidence MUST NOT simply be deleted to regain space.

---

# 100. Workspace Cleanup

Workspace cleanup MUST consider:

```text
active Runs
active Resources
pending Artifact ingestion
debug retention
Mission policy
```

A workspace referenced by an active Resource MUST NOT be deleted.

---

# 101. Orphan Detection

The node SHOULD periodically detect orphaned:

```text
processes
workspaces
Resources
leases
```

An orphan is not automatically safe to delete.

The system SHOULD classify and reconcile it based on ownership and lifecycle metadata.

---

# 102. Resource Cleanup

Resource providers SHOULD implement explicit cleanup semantics.

Examples:

```text
stop listener
close browser
terminate tunnel
remove temporary container
remove disposable Python environment
```

Cleanup failure SHOULD generate Diagnostic and lifecycle state.

---

# 103. Effects vs Local Runtime Cleanup

Target-side assessment Effects are different from node-local cleanup.

Example:

```text
remove temporary Python venv
```

is node runtime cleanup.

```text
remove account created on target
```

is Mission Effect cleanup and belongs to Workflow/Capability logic.

These MUST NOT be conflated.

---

# 104. Security of the Execution Node

The Execution Node is security-sensitive because it can execute powerful assessment tooling.

Initial hardening SHOULD include:

```text
bind transport only to intended interface
authenticated Core connection
firewall restrictions
least-necessary service privileges
restricted configuration permissions
protected runtime directories
protected Artifact spool
structured audit logging
```

---

# 105. Root Privileges

The Execution Node service SHOULD NOT run permanently as root merely for convenience.

Capabilities requiring elevated local privileges SHOULD use an explicit privilege mechanism or dedicated provider where possible.

Local privilege requirements MUST be declared.

---

# 106. Third-Party Capability Trust

v1 assumes built-in/project-controlled capability code.

Arbitrary third-party capability installation is NOT initially trusted.

Future third-party plugins SHOULD use stronger isolation.

The SDK boundary is designed so this can later be introduced.

---

# 107. Capability Upgrade

Capability implementation upgrades MUST NOT silently invalidate active Runs or Resources.

Upgrade handling SHOULD consider:

```text
existing capability version
active Runs
Resources created by previous provider version
checkpoint compatibility
```

v1 MAY require no active Runs before upgrading a capability package.

---

# 108. Provider Version Retention

Long-lived Resources MAY require their original provider implementation until closed.

The runtime SHOULD avoid unloading a provider version that still owns active Resources or Sessions.

---

# 109. Node Upgrade

Node upgrades SHOULD preserve:

```text
node identity
runtime DB
Artifact spool
persistent Workspaces
recoverable Resources
```

Schema migration MUST occur before runtime recovery.

---

# 110. Time

Execution Node SHOULD use UTC timestamps internally.

Timestamped records MUST be unambiguous.

Human UI may localize display independently.

---

# 111. Capability Reference — Nmap

End-to-end node-side flow:

```text
Invocation received
      ↓
scope validation
      ↓
dependency resolver confirms Nmap
      ↓
ExecutionContext created
      ↓
capability implementation
      ↓
Process Manager
      ↓
Nmap
      ↓
XML written to Workspace
      ↓
Artifact Client
      ↓
parser
      ↓
Observation objects
      ↓
CapabilityResult
      ↓
persist result
      ↓
deliver to Core
```

No direct Core → Nmap shortcut exists.

---

# 112. Capability Reference — Browser

```text
browser.interaction.create
      ↓
Browser Resource Provider
      ↓
Chromium launched
      ↓
Browser Resource
      ↓
Browser Session
      ↓
CapabilityRun completes

later:

browser.interaction.navigate
      ↓
Session Manager
      ↓
exclusive Session lease
      ↓
BrowserSessionDriver
      ↓
Playwright navigation
      ↓
Artifact / Observation
```

The Chromium process survives the create CapabilityRun.

---

# 113. Capability Reference — Listener

```text
listener.start
      ↓
Resource Manager
      ↓
port allocated
      ↓
provider starts listener
      ↓
Listener Resource READY
      ↓
Run completes

later:

incoming connection
      ↓
provider event
      ↓
Session Manager
      ↓
RemoteShellSession
      ↓
session.created
      ↓
Core
```

---

# 114. Capability Reference — Hash Recovery

```text
Invocation
      ↓
Artifact input
      ↓
managed hashcat process
      ↓
potential recovered secret
      ↓
Secret service
      ↓
secret_ref
      ↓
Observation
      ↓
Result
```

No target is required.

---

# 115. Capability Reference — Unknown PoC

```text
PoC Artifact
ExecutionPlan
      ↓
validate runtime requirements
      ↓
Workspace
      ↓
isolated Runtime Resource
      ↓
optional Listener Resource
      ↓
managed execution
      ↓
capture stdout/stderr/files
      ↓
Artifact
Observation
Effect
Session
Diagnostic
UNKNOWN outcome
```

The node does not need prior knowledge of the specific PoC.

---

# 116. Capability Reference — Human-Assisted PoC

```text
Run starts
      ↓
known variants attempted
      ↓
no useful result
      ↓
Checkpoint persisted
      ↓
InteractionRequest
      ↓
Run WAITING_INPUT

transport may disconnect
node may restart

      ↓

InteractionResponse arrives
      ↓
Run reconstructed
      ↓
existing Resource handles resolved
      ↓
next phase executes
      ↓
ordinary Result
```

Human assistance requires no separate Execution Node execution model.

---

# 117. Capability Reference — Privilege Transition

```text
active SessionRef
      ↓
Capability invocation
      ↓
Session lease
      ↓
managed session interaction
      ↓
evidence captured
      ↓
Effect + Observation
      ↓
possibly new Session
      ↓
Result
```

AccessContext materialization remains a Core responsibility.

---

# 118. Local Node API Boundary

Capability implementations may access node functionality only through SDK services.

They SHOULD NOT import:

```text
ProcessManager internals
Resource registry DB models
Session driver registry internals
transport implementation
local policy database
runtime SQLite repositories
```

The SDK remains the supported boundary.

---

# 119. Suggested Repository Layout

```text
execution_node/
├── app.py
├── config.py
├── identity.py
├── health.py
│
├── transport/
│   ├── base.py
│   └── mcp/
│
├── runtime/
│   ├── capability_runtime.py
│   ├── run_registry.py
│   ├── checkpoints.py
│   └── recovery.py
│
├── capabilities/
│   ├── discovery.py
│   └── loader.py
│
├── dependencies/
│   ├── resolver.py
│   └── tools.py
│
├── processes/
│   ├── manager.py
│   └── models.py
│
├── resources/
│   ├── manager.py
│   ├── registry.py
│   └── providers/
│
├── sessions/
│   ├── manager.py
│   ├── registry.py
│   └── drivers/
│
├── workspaces/
│   └── manager.py
│
├── artifacts/
│   ├── client.py
│   └── spool.py
│
├── secrets/
│   └── resolver.py
│
├── policy/
│   └── enforcement.py
│
├── persistence/
│   ├── database.py
│   └── migrations/
│
└── audit/
    └── logger.py
```

Exact filenames MAY evolve.

The boundaries SHOULD remain.

---

# 120. Node Configuration

Configuration SHOULD be explicit and validated.

Example categories:

```text
node identity
Core endpoint
transport authentication
runtime directories
database path
Artifact spool
workspace root
capability paths
tool configuration
resource limits
policy enforcement settings
logging
```

Secrets SHOULD NOT be stored directly in ordinary committed configuration files.

---

# 121. Development Mode

Development mode MAY provide:

```text
verbose logging
fake Core transport
local capability invocation
test Resource providers
```

Development conveniences MUST NOT silently weaken production policy defaults.

---

# 122. Standalone Testing

Execution Node SHOULD support integration tests without full BoberAgent Core.

A fake/control harness may:

```text
submit Invocation
provide scope projection
provide fake secret resolution
receive Events/Result
```

This allows rapid capability/runtime testing.

---

# 123. Health Checks

Health SHOULD distinguish:

```text
process alive
transport available
runtime DB available
Artifact spool writable
critical managers active
```

Tool-specific failures SHOULD normally degrade capability availability rather than make the whole node unhealthy.

---

# 124. Metrics

Useful future metrics include:

```text
active Runs
Run duration
process failures
Artifact spool size
active Resources
active Sessions
reconnect count
capability failure rate
```

Metrics are operational telemetry, not World State.

---

# 125. Execution Node Invariants

The following MUST hold:

```text
Core owns assessment meaning; node owns execution mechanics.

Transport is replaceable.

Capabilities execute through SDK services.

Capabilities do not receive direct unrestricted shell/runtime access as the normal API.

Capability metadata can be discovered without running plugin code.

Long-lived Resources may survive creator Runs.

Sessions are explicit logical objects.

Resource and Session runtime internals stay node-side.

Runs, Events and Results survive temporary Core disconnect where practical.

Duplicate Invocation delivery does not duplicate execution.

Raw evidence survives normalization failure.

Unknown interrupted state is not silently retried.

Secrets are not generally replicated to the node.

Scope is revalidated locally.

Node runtime persistence is not World State.

MCP is not the architecture.
```

---

# 126. Stress-Test Requirements

Execution Node v1 MUST naturally support:

```text
stateless Nmap execution

stateful Playwright browser

long-running listener

incoming reverse shell

Burp-backed browser workflow

CPU/GPU-heavy local cracking

unknown GitHub PoC runtime

persistent SSH/WinRM-style Session

privilege/access transition through existing Session

human-assisted suspended CapabilityRun

Core disconnect and reconnect
```

without introducing tool-specific transport or Core exceptions.

---

# 127. Implementation Rule for Coding Agents

A coding agent implementing the Execution Node MUST NOT take shortcuts such as:

```text
expose arbitrary remote shell as the node API

let plugins write the runtime database directly

use MCP tool functions as the domain architecture

store live browser/session objects in Core

discard Runs when transport disconnects

rerun a state-changing capability because result acknowledgement was lost

return filesystem paths as durable Artifact identity

make Resource lifetime equal to CapabilityRun lifetime

persist all Secret Store contents locally for convenience
```

If an implementation seems to require these shortcuts, the architecture must be reviewed.

---

# 128. Execution Node v1 Acceptance Goal

The Execution Node is successful when the Core can treat it approximately as:

```text
A node that advertises abilities,
accepts validated CapabilityInvocations,
executes them safely,
manages runtime state,
preserves evidence,
and returns structured results.
```

while remaining ignorant of:

```text
Nmap process IDs
Playwright objects
Penelope internals
venv filesystem paths
Burp process mechanics
tool-specific command syntax
```

and when temporary connection loss does not automatically destroy the logical integrity of an ongoing Mission.
