# BoberAgent Core — Capability Contract v1

**Status:** Initial normative specification
**Document:** `docs/02_CAPABILITY_CONTRACT.md`
**Contract version:** `1.x`

---

# 1. Purpose

This document defines the normative BoberAgent Capability Contract.

The contract defines how independently implemented capabilities:

* describe themselves;
* declare operations;
* accept inputs;
* are invoked;
* execute asynchronously;
* interact with platform services;
* produce results;
* create Resources and Sessions;
* report evidence;
* record target-side Effects;
* request human assistance;
* handle unknown results;
* participate in lifecycle, cancellation and recovery.

The Capability Contract is intended to remain substantially more stable than individual pentest capabilities.

---

# 2. Normative Language

The terms:

```text
MUST
MUST NOT
REQUIRED
SHOULD
SHOULD NOT
MAY
```

are normative requirements.

A compliant capability MUST satisfy all applicable MUST and MUST NOT requirements.

---

# 3. Fundamental Invariants

## 3.1 Capability identity

A Capability MUST represent a coherent system-level ability.

Capability identity MUST NOT depend on one specific underlying tool where a meaningful tool-independent ability exists.

Preferred:

```text
network.service_discovery
credential.validation
browser.interaction
```

Avoid:

```text
nmap.run
netexec.run
playwright.click
```

---

## 3.2 Capability and Workflow separation

A Capability defines:

> what the system can do.

A Workflow or Procedure defines:

> when, why and in what order capabilities should be used.

A capability implementation MUST NOT autonomously expand into unrelated assessment actions.

A capability MAY internally invoke multiple tools when those tools jointly implement one coherent ability.

---

## 3.3 World State ownership

A capability MUST NOT directly modify canonical World State.

A capability MUST NOT receive unrestricted database write access.

State flows through:

```text
CapabilityResult
      ↓
Observation Store
      ↓
State Reducer
      ↓
World State
```

---

## 3.4 Evidence preservation

Raw evidence SHOULD be persisted before normalization where practical.

Parser or normalization failure MUST NOT cause already-captured raw evidence to be discarded.

---

## 3.5 Unknown is valid

A capability MUST be able to complete successfully even when the semantic outcome remains unknown.

Unknown outcomes MUST NOT automatically be classified as execution failure.

---

# 4. Core Contract Objects

Capability Contract v1 defines the following primary objects:

```text
CapabilityDefinition
OperationDefinition

CapabilityInvocation
CapabilityRun
CapabilityResult

Observation
Finding
Artifact
Resource
Session
Effect
Diagnostic

Event
ExecutionPlan
Checkpoint

InteractionRequest
InteractionResponse
```

The following are referenced Core-domain concepts but are not defined by the Capability Contract:

```text
Mission
Scope
Asset
Identity
Credential
Secret
AccessContext
World State
```

---

# 5. CapabilityDefinition

Every capability MUST expose a CapabilityDefinition.

The definition MUST be readable without executing capability implementation code.

A CapabilityDefinition MUST contain:

```text
capability ID
contract version
implementation version
human-readable title
description
operation definitions
execution declarations
interaction-surface declarations
side-effect declarations
dependency declarations
```

Capability IDs SHOULD use hierarchical lowercase identifiers.

Example:

```text
network.service_discovery
browser.interaction
token.jwt.assessment
```

---

# 6. Versioning

The following versions MUST be independently represented:

```text
contract_version
implementation_version
```

Changing implementation logic without changing its external contract MUST NOT require a contract-version change.

Breaking schema or behavioral changes MUST require an explicit compatible contract evolution.

A capability provider MUST NOT silently expose incompatible behavior under the same declared contract version.

---

# 7. OperationDefinition

A Capability MAY expose one or more Operations.

Operations represent distinct actions belonging to one coherent capability.

Example:

```text
browser.interaction

create
navigate
click
fill
extract
screenshot
close
```

Each operation MUST define its own:

* input schema;
* required references;
* execution requirements;
* declared output classes where known.

An Operation MAY require:

```text
ResourceRef
SessionRef
ArtifactRef
CredentialRef
SecretRef
AssetRef
```

or other typed domain references.

---

# 8. Invocation

A CapabilityInvocation represents a request to execute one Operation.

An Invocation MUST identify:

```text
capability
operation
mission_ref
inputs
```

A target is NOT universally required.

Target references MUST appear only where required by the Operation input schema.

This permits target-independent capabilities such as:

```text
hash recovery
token analysis
file parsing
PoC inspection
runtime preparation
```

---

# 9. Reference Semantics

Where an existing platform object exists, an Invocation SHOULD pass a stable reference instead of duplicating object state.

Preferred:

```text
asset_ref
credential_ref
session_ref
artifact_ref
```

rather than copied host, secret or service data.

References MUST be resolved through controlled platform services.

---

# 10. CapabilityRun

Every accepted Invocation MUST produce a CapabilityRun.

CapabilityRun represents one concrete execution instance.

A Run MUST have a stable `run_id`.

---

## 10.1 Lifecycle

The standard lifecycle states are:

```text
CREATED
QUEUED
RUNNING

WAITING_INPUT
WAITING_RESOURCE
PAUSED

COMPLETED
FAILED
CANCELLED
TIMED_OUT
```

`COMPLETED`, `FAILED`, `CANCELLED` and `TIMED_OUT` are terminal.

A Run MUST NOT transition from a terminal state back to a non-terminal state.

Resumed execution after durable waiting continues the same Run where practical.

---

## 10.2 Parentage

A Run MAY reference:

```text
parent_run_ref
workflow_run_ref
```

for provenance.

Capability execution MUST NOT depend on these values being present.

---

# 11. CapabilityResult

A completed or terminal capability execution produces a CapabilityResult.

The canonical result envelope supports:

```text
execution_status
outcome

observations[]
findings[]
artifacts[]
resources[]
sessions[]
effects[]
diagnostics[]
```

Empty collections are valid.

---

# 12. Execution Status vs Outcome

Execution status describes whether the capability operation itself executed correctly.

Outcome describes the assessment meaning of that execution.

These MUST remain separate.

Example:

```text
execution_status = COMPLETED
outcome = TARGET_NOT_VULNERABLE
```

is valid.

It MUST NOT be represented as:

```text
execution_status = FAILED
```

unless the capability was unable to correctly perform the requested test.

---

# 13. Outcome

Outcome vocabularies MAY be capability-specific.

The shared platform MUST support at minimum the semantic categories:

```text
SUCCESS
NEGATIVE
PARTIAL
UNKNOWN
```

Capabilities MAY define more specific machine-readable outcome codes.

Unknown results MUST preserve enough evidence for later interpretation where possible.

---

# 14. Observation

An Observation represents something directly observed or deterministically derived from captured evidence during execution.

Observations MUST be immutable after creation.

Every Observation MUST contain or reference:

```text
observation_id
type
subject where applicable
value
producing run
timestamp
confidence where meaningful
evidence references where available
```

An Observation MUST NOT contain plaintext secrets when a Secret reference can be used.

---

# 15. Finding

A Finding represents an assessment interpretation rather than raw observation.

Example:

```text
Observation:
JWT verifies with candidate key.

Finding:
JWT signing key compromised.
```

Findings SHOULD reference supporting Observation or Artifact evidence.

A Finding SHOULD NOT be used merely as a substitute for a factual Observation.

---

# 16. Artifact

An Artifact is persistent raw or generated data.

Artifacts MUST have stable logical identifiers.

Physical filesystem paths MUST NOT serve as platform-level identities.

Artifact metadata SHOULD include:

```text
artifact_id
artifact_type
storage_ref
hash where practical
created_by_run
timestamp
metadata
```

Examples include:

```text
Nmap XML
HTTP response
screenshot
repository checkout
PoC source
PCAP
downloaded file
tool output
```

---

# 17. Secret Handling

Plain secret material MUST NOT be returned through ordinary Observation, Event or Diagnostic fields.

Capabilities MAY:

```text
resolve authorized existing secrets
```

or:

```text
store newly discovered/generated secret material
```

through the controlled Secret SDK service.

Secret storage MUST return a stable `secret_ref`.

Subsequent results and observations MAY reference that `secret_ref`.

A capability MUST NOT enumerate or read unrelated Secret Store contents.

---

# 18. Resource

A Resource represents platform-managed runtime infrastructure with an independent lifecycle.

Examples:

```text
Python environment
container
listener
browser process
Burp project
workspace
tunnel
managed process
```

Every Resource MUST have:

```text
resource_id
resource_type
provider
state
owner
lifecycle metadata
```

Resource state SHOULD use registered lifecycle semantics.

---

# 19. Session

A Session represents a persistent stateful interaction context.

Examples:

```text
SSH session
WinRM session
reverse shell
browser context
database connection
authenticated web session
```

Every Session MUST have:

```text
session_id
session_type
state
provider
ownership
```

Where applicable it SHOULD reference:

```text
target_ref
identity_ref
access_context_ref
resource_refs
```

A capability consuming a Session SHOULD depend on abstract Session capabilities rather than its original transport mechanism.

---

# 20. Resource and Session Handles

Resource and Session references are durable logical handles.

Capability implementations MUST NOT require callers to know underlying:

```text
PID
file descriptor
socket object
Playwright object
Penelope internal object
```

Runtime drivers resolve logical handles to live implementation objects.

---

# 21. Resource Concurrency

Stateful Resources and Sessions MUST declare access semantics.

The platform MUST support at least:

```text
SHARED
EXCLUSIVE
```

access.

Exclusive operations SHOULD be protected through leases.

A lease SHOULD contain:

```text
lease_id
holder_ref
expiration
```

A capability MUST NOT bypass Resource or Session locking.

---

# 22. Effect

An Effect records an actual state-changing consequence of capability execution.

This is different from a pre-execution side-effect declaration.

Definition:

```text
declared side effect
= what MAY happen

Effect
= what DID happen
```

Effects MAY represent:

```text
account creation
permission modification
service change
file modification
access transition
target configuration change
```

An Effect SHOULD include where applicable:

```text
effect_id
type
subject_ref
action
producing run
intentional
confirmed
before reference
after reference
evidence
reversibility
cleanup information
```

Capabilities that intentionally modify target state SHOULD emit Effects when the change can be verified.

---

# 23. Access Transitions

Privilege escalation and lateral movement MUST NOT require special Capability Contract modes.

They are represented through ordinary:

```text
Session
Observation
Effect
AccessContext
World State
```

mechanisms.

A capability MAY produce or verify a new Session whose AccessContext represents increased or changed authority.

Subsequent workflows may continue from that new context.

---

# 24. Diagnostic

Diagnostic represents execution-related information that is not itself target state.

Examples:

```text
DEPENDENCY_MISSING
INPUT_INVALID
TARGET_UNREACHABLE
OUTPUT_PARTIALLY_PARSED
OUTPUT_UNKNOWN
AUTHENTICATION_FAILED
POLICY_DENIED
```

Diagnostic severity SHOULD support at least:

```text
info
warning
error
```

Diagnostics MUST NOT be used to hide raw evidence.

---

# 25. Events

Capability execution is event-capable and asynchronous.

A shared event envelope MUST include:

```text
event_id
type
timestamp
mission_ref
source_ref
payload
```

Common events include:

```text
capability.run.started
capability.progress
capability.run.completed
capability.run.failed

artifact.created
observation.created
finding.created
effect.recorded

resource.ready
resource.failed

session.created
session.closed

interaction.requested
interaction.resolved
```

Capability implementations MUST NOT emit privileged Core-owned event types unless explicitly authorized.

---

# 26. Long-Running Operations

Capabilities MAY create long-running Resources without keeping one remote procedure call open indefinitely.

Example:

```text
listener.start
      ↓
CapabilityRun COMPLETED
      ↓
Listener Resource READY

... later ...

session.created
```

Long-lived activity SHOULD be represented through Resource lifecycle and Events rather than indefinitely blocked request-response calls.

---

# 27. Cancellation

Operations declaring cancellation support MUST cooperate with CapabilityRun cancellation.

Managed processes SHOULD support:

```text
graceful termination
→ timeout
→ forced termination if necessary
```

Cancellation MUST be auditable.

Cancellation MUST NOT silently remove already-created evidence.

---

# 28. Retry and Idempotency

Every operation MUST declare retry semantics.

Supported categories SHOULD include:

```text
SAFE
CONDITIONAL
UNSAFE
UNKNOWN
```

Automatic retry MUST NOT occur for `UNSAFE` or `UNKNOWN` operations unless explicitly authorized by higher-level policy.

Exploit execution MUST NOT be blindly retried merely because transport or timeout behavior was ambiguous.

---

# 29. Interaction Surface

Capabilities MUST declare the classes of execution surfaces they may use.

The shared declaration model SHOULD support:

```text
local_compute
target_network
internet_access
active_session
managed_resource
```

These declarations are used for:

* routing;
* scheduling;
* policy;
* audit.

---

# 30. Side-Effect Declaration

CapabilityDefinition MUST declare possible side effects before execution.

The shared vocabulary SHOULD cover at least:

```text
local_filesystem
local_package_installation
external_network
target_state
credential_use
local_code_execution
remote_code_execution
```

Values SHOULD distinguish states such as:

```text
none
read
write
modify
possible
expected
unknown
```

Unknown target effects MUST be representable.

---

# 31. Scope

Target-affecting operations MUST execute within Mission Scope.

Scope SHOULD be validated by both:

```text
Core
Execution Node
```

A capability MUST NOT modify scope.

A capability MUST NOT treat a caller-provided raw target string as sufficient scope authorization.

---

# 32. Policy

Capabilities declare facts about potential behavior.

Capabilities MUST NOT decide their own policy exemptions.

Capabilities MUST NOT override Policy Engine decisions.

A denied invocation MUST terminate before unauthorized execution occurs.

---

# 33. ExecutionContext

Capability implementations execute through a controlled ExecutionContext.

The SDK SHOULD expose the following capability-facing services:

```text
READ-ONLY CONTEXT
  invocation
  mission
  scope
  entities

EXECUTION SERVICES
  processes
  workspace
  resources
  sessions

DATA SERVICES
  artifacts
  secrets

CONTROL / OBSERVABILITY
  events
  logger
  cancellation
  clock
```

---

# 34. Prohibited Capability Access

A compliant capability MUST NOT receive supported APIs for:

```text
direct World State writes
arbitrary database writes
Mission mutation
Scope mutation
Policy override
Capability Registry mutation
unrestricted Secret Store enumeration
unrestricted Core Event Bus control
```

Implementation shortcuts around these boundaries are non-compliant even if they appear to work.

---

# 35. Managed Process Execution

Capability implementations SHOULD use platform Process Manager APIs instead of unmanaged subprocess execution.

Known tools SHOULD execute through managed tool execution.

Unknown or arbitrary acquired code SHOULD execute through validated ExecutionPlans and managed runtime services.

---

# 36. ExecutionPlan

ExecutionPlan represents structured execution intent for dynamic or previously unknown code.

A plan MAY specify:

```text
source artifact
runtime type
runtime version
isolation requirements
dependencies
entrypoint
argument bindings
Resource dependencies
expected results
expected effects
uncertainties
```

Typical lifecycle:

```text
DRAFT
VALIDATED
APPROVED
EXECUTED
REJECTED
```

LLMs MAY generate ExecutionPlans.

LLMs MUST NOT thereby gain unrestricted process execution rights.

---

# 37. Unknown PoC Handling

Unknown third-party PoCs MUST be representable without registering a new special-case Core pathway for each PoC.

Typical handling:

```text
Artifact
→ inspect
→ ExecutionPlan
→ validate
→ policy
→ prepare runtime
→ execute
→ interpret
```

A PoC execution MAY produce any combination of:

```text
Observation
Finding
Artifact
Resource
Session
Effect
Diagnostic
UNKNOWN outcome
```

---

# 38. Human Interaction

A capability MAY request external assistance while still executing.

It MUST do so through an InteractionRequest.

A capability MUST NOT implement private blocking stdin interaction as part of the platform contract.

---

## 38.1 InteractionRequest

InteractionRequest MUST contain:

```text
interaction_id
run_ref
interaction type
human-readable description
input schema
resume semantics
```

Supported interaction types SHOULD include:

```text
confirmation
choice
text_input
structured_form
secret_input
artifact_input
```

A Run waiting for interaction enters:

```text
WAITING_INPUT
```

---

## 38.2 InteractionResponse

The Interaction Router supplies an InteractionResponse.

Response validation MUST use the declared InteractionRequest schema.

After successful response handling, the Run MAY resume `RUNNING`.

---

## 38.3 Human assistance vs approval

Human assistance and Policy Approval are distinct.

```text
InteractionRequest:
"I need information or help to continue."

Policy Approval:
"I know what action I intend to perform; is it permitted?"
```

Implementations MUST NOT use InteractionRequest as a workaround for Policy Engine decisions.

---

# 39. Checkpoint

A capability that may wait durably SHOULD support explicit checkpointing.

Checkpoint MUST contain sufficient state to resume logically without requiring preservation of an in-memory Python stack.

Checkpoint data MAY include:

```text
phase
completed attempts
Artifact references
Resource references
Session references
pending InteractionRequest
next logical state
```

Checkpoint data MUST NOT contain unnecessary plaintext secrets.

---

# 40. Runtime State vs World State

Internal runtime state MUST NOT automatically become World State.

Examples of browser-internal state:

```text
DOM objects
open page handles
navigation stack
cookies
localStorage
```

remain Session/Resource runtime state unless relevant information is emitted as an Observation or securely stored value.

---

# 41. Secret-Producing Capabilities

Capabilities such as:

```text
hash recovery
token generation
key extraction
credential recovery
```

MAY generate sensitive values.

Such values MUST be written through the controlled Secret service.

The returned platform representation SHOULD be:

```text
secret_ref
```

A resulting Observation may state that a secret was recovered and reference the secure object without exposing its plaintext value.

---

# 42. Artifact-Producing Capabilities

A capability SHOULD persist material evidence through the Artifact service rather than exposing unmanaged file paths.

Raw tool output SHOULD be captured as Artifact where operationally useful.

A normalizer MAY subsequently derive Observations from that Artifact.

---

# 43. Capability Results and State Reduction

CapabilityResult does not directly define canonical World State mutation.

State processing MAY consume:

```text
Observations
Effects
Session lifecycle
Resource lifecycle
secure references
```

to update Core-owned domain state.

No capability-specific direct state mutation hook is permitted in Contract v1.

---

# 44. Capability Discovery

Execution Nodes SHOULD advertise available CapabilityDefinitions dynamically.

The Core MUST NOT require manual hard-coded registration of every capability implementation.

Discovery data MUST be validated before registry admission.

---

# 45. Capability Dependencies

CapabilityDefinition MAY declare dependencies.

Dependencies MUST distinguish:

```text
capability dependencies
tool dependencies
runtime dependencies
resource requirements
```

A tool dependency is not equivalent to a capability dependency.

Example:

```text
credential.validation
```

may have an implementation requiring:

```text
nxc
```

while a Workflow may require the separate capability:

```text
network.service_discovery
```

These relationships MUST NOT be conflated.

---

# 46. Capability Package

A standard capability package SHOULD use a structure similar to:

```text
capability_name/
├── capability.yaml
├── schemas/
│   ├── operation.input.schema.json
│   └── operation.result.schema.json
├── implementation/
├── adapters/
├── tests/
│   ├── contract/
│   └── integration/
└── README.md
```

Tool-specific concerns SHOULD remain inside implementation or adapter layers.

---

# 47. Compliance Tests

A capability MUST pass contract validation before being considered installable/enabled.

Compliance SHOULD verify at least:

```text
manifest validity
contract-version compatibility
input schema validity
result schema validity

dependency declarations
side-effect declarations
retry semantics
scope behavior

Artifact provenance
secret handling
Resource/Session lifecycle use

cancellation behavior where declared
InteractionRequest behavior where used
Checkpoint validity where required

absence of direct World State mutation
```

Integration tests MAY impose capability-specific additional requirements.

---

# 48. Reference Capability: Network Service Discovery

The initial reference capability is:

```text
network.service_discovery
```

Its first implementation may use Nmap.

The normative flow is:

```text
Invocation
→ Run
→ managed process execution
→ raw Artifact
→ deterministic parser
→ Observation(s)
→ CapabilityResult
→ Observation Store
→ State Reducer
```

Nmap-specific output MUST NOT become part of Core architecture.

---

# 49. Reference Capability: Browser Interaction

A stateful browser MUST fit the same contract.

Expected pattern:

```text
browser.interaction.create
    ↓
Browser Resource
Browser Session

browser.interaction.navigate
    ↓
SessionRef
    ↓
Observation / Artifact
```

Browser-specific runtime state remains behind Resource/Session drivers.

---

# 50. Reference Capability: Listener and Incoming Session

Expected pattern:

```text
listener.start
    ↓
Listener Resource

... later ...

session.created event
    ↓
Remote Session
```

No permanently open capability RPC is required.

---

# 51. Reference Case: Local Analysis

Target-independent local operations such as:

```text
hash recovery
JWT analysis
cookie analysis
PoC source inspection
```

MUST be valid capabilities without artificial Target references.

---

# 52. Reference Case: Access Transition

Privilege or lateral access transitions MUST fit:

```text
existing Session / AccessContext
      ↓
Capability
      ↓
Observation + Effect
      ↓
new or updated Session / AccessContext
      ↓
World State
```

No privilege-escalation-specific Core exception is permitted.

---

# 53. Reference Case: Human-Assisted PoC

A PoC that cannot proceed autonomously MUST be able to:

```text
RUNNING
→ create InteractionRequest
→ checkpoint
→ WAITING_INPUT
→ receive valid response
→ RUNNING
→ produce ordinary CapabilityResult
```

Higher-level workflows MAY consume the final result identically to autonomous success.

---

# 54. Contract Stress-Test Requirement

Any future major Contract revision SHOULD be checked against at least the following scenarios:

```text
1. stateless network discovery
2. stateful Playwright browser
3. long-running listener + incoming shell
4. Burp-backed interactive assessment
5. unknown acquired PoC
6. persistent remote session
7. vertical/horizontal access transition
8. local hash/JWT processing
9. human-assisted execution
```

If one scenario requires a unique Core exception, the abstraction SHOULD be reconsidered before adding the exception.

---

# 55. Forbidden Architectural Shortcuts

The following are explicitly non-compliant:

```text
Core directly invoking pentest CLI tools

capability directly updating World State

LLM directly executing arbitrary shell commands outside managed execution

capability storing canonical identity via local filesystem path

plaintext secrets in ordinary event streams

workflow logic embedded invisibly inside unrelated capability implementations

human interaction implemented through private blocking stdin

special Core code added solely because one tool behaves differently
```

---

# 56. Contract Evolution

When a required behavior cannot be expressed under this Contract:

1. implementation MUST NOT silently work around the contract;
2. the conflict SHOULD be documented;
3. existing stress-test scenarios SHOULD be reevaluated;
4. an ADR SHOULD describe the proposed semantic change;
5. Contract documentation and schemas MUST be updated before dependent implementation is treated as canonical.

---

# 57. Capability Contract v1 Design Goal

A developer or coding agent should be able to receive:

```text
Capability Contract
Capability SDK
schemas
reference implementations
compliance tests
```

and implement a new capability without needing internal knowledge of BoberAgent Core.

If implementation regularly requires knowledge of Core internals, the capability boundary is considered insufficient and should be reviewed.
