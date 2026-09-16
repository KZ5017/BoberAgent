# BoberAgent Core — Reference Capabilities v1

**Status:** Reference specification and implementation guidance
**Document:** `docs/08_REFERENCE_CAPABILITIES.md`
**Related:** `02_CAPABILITY_CONTRACT.md`, `03_CAPABILITY_SDK.md`, `04_WORLD_STATE_MODEL.md`, `05_WORKFLOW_AND_REASONING.md`, `07_EXECUTION_NODE.md`

---

# 1. Purpose

This document defines reference Capability designs for BoberAgent.

Its purpose is to demonstrate how radically different security operations fit the same Capability Contract and SDK without introducing special-case Core architecture.

These examples are intended to:

* guide capability authors;
* guide coding agents;
* validate architectural consistency;
* establish preferred package patterns;
* clarify Capability granularity;
* demonstrate Result, Resource, Session and Effect semantics.

This document does not replace the normative Capability Contract.

If an example conflicts with `02_CAPABILITY_CONTRACT.md`, the Contract takes precedence.

---

# 2. Reference Set

The initial reference set contains:

```text
1. network.service_discovery
2. browser.interaction
3. listener.management
4. session.command_interaction
5. web.proxy_assessment
6. token.jwt_assessment
7. secret.hash_recovery
8. poc.candidate_execution
9. access.transition
```

Together these exercise:

```text
one-shot execution
stateful execution
long-lived Resources
persistent Sessions
local-only computation
target-facing activity
secret handling
Artifact processing
human interaction
unknown third-party code
target-side Effects
privilege/access transitions
```

---

# 3. Common Package Structure

Reference capabilities SHOULD generally resemble:

```text
capabilities/
└── <capability_name>/
    ├── capability.yaml
    │
    ├── schemas/
    │   ├── <operation>.input.schema.json
    │   └── <operation>.result.schema.json
    │
    ├── implementation/
    │   ├── capability.py
    │   └── ...
    │
    ├── adapters/
    │   └── ...
    │
    ├── tests/
    │   ├── contract/
    │   ├── unit/
    │   └── integration/
    │
    └── README.md
```

Not every capability requires an `adapters/` directory.

---

# 4. Reference 1 — `network.service_discovery`

## 4.1 Purpose

Discover reachable network services on a scoped Asset.

This is the first bootstrap Capability.

Initial implementation:

```text
Nmap
```

Nmap is an implementation detail.

---

## 4.2 Capability Identity

```yaml
id: network.service_discovery

contract_version: "1.0"
implementation_version: "0.1.0"

operations:
  - discover
```

---

## 4.3 Execution Characteristics

```yaml
execution:
  duration: one_shot
  interaction: stateless
  scheduling: asynchronous

interaction_surface:
  local_compute: true
  target_network: true
  internet_access: false
  active_session: false
  managed_resource: false
```

---

## 4.4 Inputs

Conceptually:

```yaml
target_ref: asset-17

profile: baseline

timeout: 600
```

The input MUST use a scoped Asset reference.

The implementation resolves the address through `ctx.entities`.

---

## 4.5 Execution

```text
AssetRef
   ↓
scope validation
   ↓
ProcessService
   ↓
Nmap
   ↓
Workspace
   ↓
raw XML
   ↓
Artifact
   ↓
Nmap XML adapter
   ↓
Observations
```

---

## 4.6 Outputs

Typical Observations:

```text
host reachability
TCP/22 open
TCP/80 open
TCP/445 open
service banner/product/version
```

Typical Artifacts:

```text
network_scan.nmap_xml
process.stdout
process.stderr
```

No Session is normally produced.

No target-side Effect is normally produced.

---

## 4.7 Important Boundary

This Capability MUST NOT decide:

```text
445 open
→ run SMB enumeration
```

That decision belongs to Workflow/Procedure logic.

---

## 4.8 Acceptance Tests

Must verify:

```text
invalid AssetRef rejected
out-of-scope Asset rejected
Nmap dependency missing handled correctly
XML preserved as Artifact
parser failure preserves raw evidence
Observations contain provenance
cancellation works
duplicate Run delivery does not repeat execution
```

---

# 5. Reference 2 — `browser.interaction`

## 5.1 Purpose

Create and operate a persistent browser interaction context.

Initial provider:

```text
Playwright + Chromium
```

---

## 5.2 Capability Identity

```yaml
id: browser.interaction

operations:
  - create
  - navigate
  - click
  - fill
  - extract
  - screenshot
  - close
```

---

# 6. Browser Resource Model

The browser engine is a Resource.

Example:

```text
resource://browser-process/17
```

The stateful browsing context is a Session.

Example:

```text
session://browser/44
```

This distinction is intentional.

---

# 7. Browser Create

Input MAY include:

```yaml
engine: chromium
headless: true

proxy_ref: null
```

Output:

```text
BrowserProcess Resource
Browser Session
```

The creating CapabilityRun may complete while both remain active.

---

# 8. Browser Navigate

Input:

```yaml
session_ref: session-browser-44

url: https://target.example/
```

Flow:

```text
SessionRef
   ↓
Session Manager
   ↓
exclusive lease
   ↓
BrowserSessionDriver
   ↓
navigation
   ↓
relevant evidence
```

Possible output:

```text
Observation:
page loaded

Observation:
page title

Artifact:
screenshot

Artifact:
selected HTTP/network evidence
```

---

# 9. Browser Runtime State

The following remain Session-internal unless assessment-relevant:

```text
page objects
DOM handles
navigation stack
tab objects
JavaScript runtime objects
```

Cookies or localStorage values SHOULD NOT automatically become World State.

Relevant authentication material may be securely promoted through the appropriate Secret/Credential mechanisms.

---

# 10. Browser Locking

Operations such as:

```text
navigate
click
fill
```

normally require:

```text
EXCLUSIVE
```

Session access.

Concurrent conflicting navigation MUST be prevented.

---

# 11. Browser Acceptance Tests

Must cover:

```text
create Resource + Session
Session survives creator Run
navigate using existing Session
exclusive locking
screenshot Artifact creation
browser close
lost browser process → Session/Resource update
runtime state does not leak into World State indiscriminately
```

---

# 12. Reference 3 — `listener.management`

## 12.1 Purpose

Create and manage inbound connection listeners.

Possible provider:

```text
Penelope
```

The Capability identity MUST NOT be:

```text
penelope.run
```

---

## 12.2 Operations

```yaml
id: listener.management

operations:
  - start
  - inspect
  - stop
```

---

# 13. Listener Start

Input MAY include:

```yaml
protocol: tcp

bind:
  address: 0.0.0.0
  port: auto

callback:
  address: configured-or-derived
```

The distinction between:

```text
bind address
callback/reachable address
```

MUST be preserved.

---

# 14. Listener Output

`start` normally produces:

```text
Listener Resource
```

Example:

```yaml
resource_type: listener

state: READY

properties:
  protocol: tcp
  bind_port: 4444
  callback_address: ...
```

The Run then completes.

---

# 15. Incoming Connection

Later:

```text
target connection
       ↓
Listener provider
       ↓
Session Manager
       ↓
Remote Session
       ↓
session.created Event
```

This event is independent of the already-completed `listener.start` Run.

---

# 16. Listener Resource Lifetime

The Listener Resource MAY be:

```text
Run-owned initially
```

and then promoted to:

```text
Workflow-owned
or
Mission-owned
```

when needed beyond creator Run lifetime.

---

# 17. Listener Acceptance Tests

Must verify:

```text
managed port allocation
port conflict prevention
Resource survives creator Run
incoming connection creates Session
disconnect/reconnect behavior
stop closes Resource
node restart reconciliation
callback address differs from bind address when configured
```

---

# 18. Reference 4 — `session.command_interaction`

## 18.1 Purpose

Execute operations through an existing command-capable Session.

This Capability MUST NOT care whether the Session originated from:

```text
SSH
WinRM
reverse shell
another execution mechanism
```

provided the Session advertises compatible operations.

---

## 18.2 Operations

```text
execute
upload
download
```

A narrower first implementation MAY begin with:

```text
execute
```

---

# 19. Command Execution Input

```yaml
session_ref: session-88

command: <structured operation input>

timeout: 60
```

The exact command content is domain input.

The Capability consumes an existing Session.

---

# 20. Session Requirement

Precondition:

```text
Session state = ACTIVE
```

and Session capabilities include:

```text
command_execute
```

The Session is acquired through:

```text
ctx.sessions.acquire(...)
```

---

# 21. Output

Possible outputs:

```text
command stdout Artifact
command stderr Artifact
Observation
Diagnostic
Effect where a target-side change was intentionally performed
```

---

# 22. Important Boundary

Generic command execution is powerful.

Strategic orchestration MUST NOT devolve into:

```text
LLM continuously invents shell commands
```

when a structured Capability already exists.

Preferred:

```text
linux.local_baseline
```

rather than repeatedly using arbitrary command execution to reinvent its logic.

Command interaction is an infrastructure Capability, not the default replacement for all higher-level capabilities.

---

# 23. Session Interaction Acceptance Tests

Must verify:

```text
Session type independence
Session capability validation
exclusive lease where required
timeout
cancellation
output Artifact creation
Session loss handling
no direct World State mutation
```

---

# 24. Reference 5 — `web.proxy_assessment`

## 24.1 Purpose

Represent proxy-assisted interactive web assessment.

Possible implementation may use:

```text
Burp Suite
browser integration
HTTP capture/replay
```

Burp MUST remain behind provider/runtime abstractions.

---

# 25. Resource Model

Possible Resources:

```text
BurpProject
BurpProxy
```

Possible Sessions:

```text
BrowserSession
AuthenticatedWebSession
```

These may reference each other.

---

# 26. Example Create Flow

```text
web.proxy_assessment.create
        ↓
BurpProject Resource
        ↓
BurpProxy Resource
```

A browser may later be created with:

```text
proxy_ref = BurpProxy Resource
```

---

# 27. Assessment Operations

Possible future operations:

```text
traffic.list
request.inspect
request.replay
response.inspect
```

These belong to one coherent proxy-assessment ability.

---

# 28. Output

Possible:

```text
HTTP request Artifact
HTTP response Artifact
Observation
Finding
```

Captured authentication secrets require Secret handling.

---

# 29. Burp Acceptance Criteria

Architecture must prove:

```text
no Burp-specific Core logic
Burp process represented as Resource
browser can reference proxy Resource
traffic survives as Artifact
Resources can outlive individual Runs
```

---

# 30. Reference 6 — `token.jwt_assessment`

## 30.1 Purpose

Analyze JWT material locally.

This reference proves that a Capability does not require direct target interaction.

---

## 30.2 Operations

Possible:

```text
inspect
verify_candidate_key
```

Token generation SHOULD preferably be a separate coherent operation/capability if its semantics differ materially.

---

# 31. JWT Inspect

Input:

```yaml
token_artifact_ref: artifact-jwt-17
```

Potential output Observations:

```text
algorithm = HS256
header fields
claim structure
expiration metadata
signature structure
```

Sensitive token material remains protected according to classification.

---

# 32. Candidate Key Verification

Input:

```yaml
token_artifact_ref: artifact-jwt-17
candidate_secret_ref: secret-91
```

Execution:

```text
local compute only
```

Possible Observation:

```text
candidate secret verifies token signature
```

Possible Finding:

```text
JWT signing secret compromised
```

---

# 33. JWT → New Access Flow

Separate workflow:

```text
captured token
+
candidate secret
      ↓
JWT assessment
      ↓
secret confirmed
      ↓
token creation capability
      ↓
new Secret/Credential
      ↓
target-facing authentication
      ↓
Web Session
```

This is a Workflow.

It MUST NOT be hidden inside `token.jwt_assessment`.

---

# 34. JWT Acceptance Tests

Must demonstrate:

```text
no target required
SecretRef rather than plaintext input
secret value absent from logs/result
structured Observations
Finding evidence links
no automatic target authentication
```

---

# 35. Reference 7 — `secret.hash_recovery`

## 35.1 Purpose

Attempt local recovery of plaintext or equivalent material from supported hashes.

Possible providers:

```text
hashcat
John
```

---

# 36. Capability Identity

```yaml
id: secret.hash_recovery

operations:
  - recover
```

This is preferable to:

```text
hashcat.run
```

---

# 37. Input

Conceptually:

```yaml
hash_artifact_ref: artifact-72

hash_type:
  known: true
  value: ntlm

strategy_ref: optional
```

A future strategy object may select wordlists/rules without exposing those concerns as Core architecture.

---

# 38. Execution Characteristics

```text
local_compute = true
target_network = false
```

Potentially:

```text
long_running
CPU/GPU intensive
asynchronous
```

---

# 39. Successful Result

Recovered secret material MUST go through:

```text
ctx.secrets.store(...)
```

Result contains:

```text
secret_ref
```

not plaintext.

Observation:

```text
candidate hash material successfully resolved
```

World State may subsequently materialize/update Credential state.

---

# 40. Negative Result

If the cracking strategy exhausts correctly without recovery:

```text
execution_status = COMPLETED

outcome = NEGATIVE
```

This is not execution failure.

---

# 41. Hash Recovery Acceptance Tests

Must cover:

```text
long-running process
cancellation
Resource limits
GPU/CPU class where applicable
Secret Store integration
no plaintext output leak
negative outcome
Artifact evidence
```

---

# 42. Reference 8 — `poc.candidate_execution`

## 42.1 Purpose

Execute a previously acquired and inspected PoC candidate through a validated ExecutionPlan.

This is deliberately generic.

The Capability MUST NOT assume:

```text
Python
reverse shell
RCE
GitHub
one specific CVE
```

---

# 43. Required Inputs

Conceptually:

```yaml
exploit_candidate_ref: exploit-candidate-17

source_artifact_ref: artifact-repository-91

execution_plan_ref: plan-44

target_ref: asset-or-application-ref

optional_resource_refs:
  - listener
  - runtime
```

Inputs depend on the validated ExecutionPlan.

---

# 44. Preconditions

At minimum:

```text
ExecutionPlan VALIDATED

policy permits execution

target in scope

required runtime Resources available

required Artifacts available
```

If policy requires explicit approval:

```text
ExecutionPlan APPROVED
```

must also be satisfied.

---

# 45. Runtime Preparation

The execution path MAY require:

```text
Workspace
PythonEnvironment Resource
Container Resource
compiler
listener
other runtime dependency
```

These are resolved through SDK services.

---

# 46. Execution

Conceptually:

```text
PoC Artifact
+
ExecutionPlan
      ↓
managed Workspace
      ↓
managed Runtime
      ↓
ProcessService.execute_plan(...)
      ↓
evidence capture
```

The Capability implementation does not convert the ExecutionPlan into an unrestricted opaque shell escape.

---

# 47. Valid PoC Outcomes

The Result MAY contain any combination of:

```text
Observation
Finding
Artifact
Session
Resource
Effect
Diagnostic
```

Outcome may be:

```text
SUCCESS
NEGATIVE
PARTIAL
UNKNOWN
```

---

# 48. Unknown Result

Example:

```text
process exited
target responded unexpectedly
no clear success indicator
no clear failure indicator
```

Correct response:

```text
COMPLETED
+
UNKNOWN
+
raw evidence
```

not fabricated success or failure.

---

# 49. Human-Assisted PoC

Suppose known execution variants fail.

The Run MAY:

```text
persist Checkpoint
      ↓
InteractionRequest
      ↓
WAITING_INPUT
```

Example request:

```text
Known execution variants did not produce the expected result.

Choose:
- retry with alternate known configuration
- provide custom parameter
- provide modified Artifact
- stop this branch
```

After response:

```text
Run resumes
```

using the same logical `run_id`.

---

# 50. Human Assistance Provenance

The final CapabilityResult is ordinary.

However, Run/Decision history SHOULD record:

```text
human assistance occurred
interaction ID
human-supplied input reference
```

The next Workflow step does not require a special human-assisted success type.

---

# 51. PoC Acceptance Tests

Must cover:

```text
unknown runtime type support through ExecutionPlan
Workspace isolation
optional listener Resource
UNKNOWN outcome
human wait/resume
Checkpoint persistence
node restart during WAITING_INPUT
Effect reporting
Session creation
unsafe automatic retry prevention
raw evidence retention
```

This is one of the primary architecture stress tests.

---

# 52. Reference 9 — `access.transition`

## 52.1 Purpose

Represent an operation intended to obtain a changed AccessContext.

This reference covers:

```text
vertical privilege extension
horizontal access extension
identity transition
service/account control transition
```

without adding a special privilege-escalation execution model.

---

# 53. Capability Granularity

`access.transition` is a reference abstraction.

Actual concrete capabilities MAY be more specific where a coherent reusable ability exists.

For example:

```text
access.remote_authentication
service.control_assessment
identity.permission_transition
```

The Core MUST NOT require one universal monolithic `privilege_escalation()` capability.

---

# 54. Inputs

Possible:

```yaml
session_ref: session-41

target_ref: host-17

current_access_context_ref: access-12

candidate_transition_ref: candidate-88
```

The transition candidate may have originated from:

```text
Procedure
local enumeration
Finding
Reasoner
human input
```

---

# 55. Execution

Conceptually:

```text
current Session
      ↓
current AccessContext
      ↓
transition capability
      ↓
target interaction
      ↓
verification
```

---

# 56. Outputs

Successful transition may produce:

```text
Observation:
new authority verified

Effect:
target state changed

Session:
new elevated or alternate interaction context
```

The State Reducer then materializes the new AccessContext.

The capability MUST NOT directly update AccessContext state.

---

# 57. New Account Example

If assessment logic deliberately creates a new account:

Result SHOULD include:

```text
Effect:
account created

Observation:
account authentication verified

possibly Credential/Secret reference

possibly new Session
```

Cleanup metadata SHOULD identify how the assessment-induced account can later be removed.

---

# 58. Service Control Example

If an assessment changes service state/configuration:

```text
Effect:
service configuration modified

Observation:
resulting execution/access behavior verified
```

Cleanup MAY require restoring original service configuration.

---

# 59. Horizontal Transition Example

Current state:

```text
Identity A
AccessContext on Host X
```

Capability validates usable access to Host Y.

Result:

```text
Session on Host Y
```

Reducer creates:

```text
AccessContext:
Identity A
Host Y
```

No separate lateral-movement engine is required.

---

# 60. Access Transition Acceptance Tests

Must verify:

```text
existing Session consumption
AccessContext used as input context only
target Effect reporting
new Session creation
new AccessContext materialized only by Core
cleanup metadata
negative transition result
unsafe retry prevention
```

---

# 61. Cross-Reference Scenario — Credential Recovery to New Session

The following complete sequence must require no architectural exception:

```text
Artifact containing hash
      ↓
secret.hash_recovery
      ↓
SecretRef
      ↓
World State Credential candidate
      ↓
credential.validation
      ↓
validated Credential
      ↓
remote authentication capability
      ↓
Session
      ↓
AccessContext
```

Each Capability remains independently useful.

---

# 62. Cross-Reference Scenario — JWT to Authenticated Browser

```text
captured JWT Artifact
+
candidate signing Secret
      ↓
token.jwt_assessment
      ↓
Finding + verified Secret relation
      ↓
token generation
      ↓
new token Secret/Credential
      ↓
browser/web authentication
      ↓
authenticated Browser Session
```

The local-analysis stage and target-facing stage remain separate.

---

# 63. Cross-Reference Scenario — CVE to Session

```text
Technology/version
      ↓
vulnerability research
      ↓
Vulnerability candidate
      ↓
PoC research
      ↓
ExploitCandidate
      ↓
repository Artifact
      ↓
PoC inspection
      ↓
ExecutionPlan
      ↓
runtime preparation
      ↓
listener Resource if required
      ↓
poc.candidate_execution
      ↓
Session
      ↓
AccessContext
```

The Workflow does not need prior knowledge of the PoC's language or payload mechanism.

---

# 64. Cross-Reference Scenario — Human Rescue

```text
PoC Run
      ↓
known variants fail
      ↓
no new deterministic fallback
      ↓
InteractionRequest
      ↓
human provides modified parameter/Artifact
      ↓
Run resumes
      ↓
Session created
      ↓
normal Workflow continues
```

Human assistance does not require restarting the entire Mission.

---

# 65. Capability Design Questions

Before creating a new Capability, the author SHOULD answer:

```text
What coherent system ability does this represent?

Would another Workflow want to reuse this ability?

Is this actually a Procedure rather than a Capability?

Is the identity tool-independent?

What inputs does it really require?

Does it require a target?

Does it consume Resource or Session handles?

What durable outputs can it produce?

Can it change target state?

What side effects must be declared?

Is execution idempotent?

Can it wait?

Can it be cancelled?

Can it survive restart?

What raw evidence should be preserved?
```

---

# 66. Capability vs Procedure Test

Consider proposed feature:

```text
enumerate SMB
then LDAP
then Kerberos
then validate credentials
```

This is most likely:

```text
Procedure
```

because it orchestrates several independently meaningful abilities.

---

# 67. Capability vs Tool Adapter Test

Consider:

```text
parse Nmap XML
```

This is normally:

```text
tool adapter / normalizer
```

not a standalone Capability.

---

# 68. Capability vs Resource Provider Test

Consider:

```text
launch Chromium and keep it alive
```

This may be implemented by:

```text
Browser Resource Provider
```

used by:

```text
browser.interaction
```

rather than exposing process management as an assessment Capability.

---

# 69. Capability vs Session Driver Test

Consider:

```text
send command to Penelope connection
```

This is normally:

```text
RemoteShellSessionDriver
```

behind a generic Session-consuming Capability.

Penelope internals should not leak into orchestration.

---

# 70. Capability Result Guidance

A Capability SHOULD produce the most semantically meaningful structured result.

Use:

```text
Observation
```

for measured facts.

Use:

```text
Finding
```

for interpreted security conclusions.

Use:

```text
Artifact
```

for durable evidence/data.

Use:

```text
Resource
```

for managed runtime infrastructure.

Use:

```text
Session
```

for persistent interaction contexts.

Use:

```text
Effect
```

for actual assessment-induced target changes.

Use:

```text
Diagnostic
```

for execution/runtime information.

---

# 71. Result Anti-Pattern

Avoid returning only:

```json
{
  "success": true,
  "output": "..."
}
```

This throws away the semantic structure BoberAgent requires.

---

# 72. Unknown Output Guidance

When structured interpretation is incomplete:

```text
preserve raw Artifact
emit known Observations
emit Diagnostic
return UNKNOWN/PARTIAL outcome
```

Do not make downstream logic parse arbitrary stdout unless no better mechanism exists.

---

# 73. Capability Internal Tool Fallback

A Capability MAY have multiple internal implementations or tool fallbacks when they provide the same coherent ability.

Example:

```text
credential.validation

primary:
NetExec

fallback:
another compatible implementation
```

This MAY remain internal if switching does not materially change Workflow semantics.

---

# 74. When Tool Choice Becomes Workflow-Relevant

If alternative techniques have meaningfully different:

```text
risk
side effects
prerequisites
assessment meaning
```

they SHOULD NOT be hidden as interchangeable implementation fallbacks.

They may deserve separate capability operations or Workflow decisions.

---

# 75. Side-Effect Reference Table

Typical reference declarations:

| Reference                     | Target interaction            | Target state change          |
| ----------------------------- | ----------------------------- | ---------------------------- |
| `network.service_discovery`   | active/read                   | normally none                |
| `browser.interaction`         | active                        | possible depending operation |
| `listener.management`         | none until inbound connection | none                         |
| `session.command_interaction` | active                        | depends on command           |
| `token.jwt_assessment`        | none                          | none                         |
| `secret.hash_recovery`        | none                          | none                         |
| `poc.candidate_execution`     | active                        | possible/unknown             |
| `access.transition`           | active                        | possible/expected            |

Concrete manifests MUST be more precise than this summary.

---

# 76. Retry Reference Table

Typical starting semantics:

| Reference                  | Idempotency      |
| -------------------------- | ---------------- |
| service discovery          | CONDITIONAL      |
| JWT local inspect          | SAFE             |
| candidate-key verification | SAFE             |
| hash recovery              | SAFE/CONDITIONAL |
| browser navigation         | CONDITIONAL      |
| listener start             | CONDITIONAL      |
| arbitrary PoC              | UNKNOWN          |
| target access transition   | UNSAFE/UNKNOWN   |

Capability manifests define the authoritative value.

---

# 77. Human Interaction Suitability

Human Interaction SHOULD be available where it adds meaningful recovery.

Particularly relevant:

```text
unknown PoC adaptation
ambiguous runtime setup
manual Artifact modification
complex interactive web flow
parameter selection
```

It SHOULD NOT be used merely to avoid implementing deterministic validation.

---

# 78. Reference Testing Strategy

Every reference capability SHOULD have three test levels.

### Contract tests

Verify architectural compliance.

### Unit tests

Verify capability-specific parsing/logic.

### Integration tests

Exercise real provider/tool behavior in controlled fixtures.

---

# 79. Contract Test Examples

Common assertions:

```text
manifest valid
operation schemas valid
CapabilityResult validates
Artifact provenance exists
secret handling compliant
World State write unavailable
scope enforced
cancellation declared correctly
retry semantics declared
```

---

# 80. Integration Fixture Safety

Integration tests SHOULD use:

```text
local fixtures
test containers
controlled lab services
authorized lab targets
```

Tests MUST NOT depend on arbitrary internet targets.

---

# 81. Golden Artifacts

Tool adapters SHOULD have regression fixtures.

Example:

```text
tests/fixtures/nmap/
├── normal.xml
├── malformed.xml
├── host_down.xml
└── version_detection.xml
```

This allows parsing changes without repeatedly launching real tools.

---

# 82. Stateful Test Fixtures

Browser, listener and Session capabilities require lifecycle tests.

Example:

```text
create
→ use
→ disconnect
→ reconnect
→ close
```

Resource lifetime must be tested independently from CapabilityRun lifetime.

---

# 83. Restart Tests

At least the following reference cases SHOULD eventually be tested across Execution Node restart:

```text
persisted Python environment Resource
WAITING_INPUT PoC Run
Artifact spool pending sync
lost browser Session
completed Result pending delivery
```

---

# 84. Reference Capability Documentation

Every production capability SHOULD document:

```text
purpose
operations
inputs
outputs
side effects
dependencies
Resources/Sessions used
retry semantics
failure semantics
examples
known limitations
```

This README is for maintainers.

The machine-readable manifest remains authoritative.

---

# 85. Capability Naming

Names SHOULD describe system abilities.

Preferred:

```text
network.service_discovery
token.jwt_assessment
secret.hash_recovery
browser.interaction
listener.management
```

Avoid project-brand or tool-brand naming where it reduces semantic clarity.

Existing Bober-prefixed tools may remain implementation projects, but their logic should map into professionally named capabilities.

---

# 86. Existing BoberAutoScanner Mapping

BoberAutoScanner SHOULD be treated as a source of proven implementation logic.

It SHOULD NOT become:

```text
boberautoscanner.run
```

as one monolithic capability.

Its logic may map into capabilities such as:

```text
network.service_discovery
ad.smb_baseline
ad.ldap_baseline
service-specific enumeration
```

and Procedures that orchestrate them.

---

# 87. Existing BoberExec Mapping

The BoberExec concept maps primarily to:

```text
credential.validation
```

The redesigned implementation should consume:

```text
CredentialRef
known ServiceRefs
```

from World State rather than parsing Nmap files.

It returns normalized per-service validation results.

---

# 88. Existing BoberCrawler Mapping

BoberCrawler may provide implementation patterns for:

```text
web.crawl
browser-assisted discovery
```

and Playwright integration.

Stateful interactive browsing should use Resource/Session abstractions rather than treating each browser invocation as a standalone crawler process.

---

# 89. Reference Architecture Validation

After these reference designs, the Capability Contract must be able to express:

```text
Nmap scan
browser automation
listener
remote shell
proxy-backed web assessment
local crypto/token analysis
GPU/CPU cracking
unknown PoC
access transition
human assistance
```

without introducing:

```text
special Core execution paths
tool-specific World State writes
transport-specific Capability types
```

This is the primary purpose of this document.

---

# 90. Reference Capability Invariants

All reference capabilities obey:

```text
Capability identity is tool-independent where meaningful.

Capabilities do not mutate World State directly.

Raw evidence is preserved.

Target-independent operations are valid.

Resources may outlive Runs.

Sessions are explicit.

Secrets use SecretRefs.

Actual target changes use Effects.

Unknown is a valid outcome.

Human assistance is resumable.

Workflow strategy remains outside capability internals.

Execution Node owns runtime mechanics.

Core owns assessment meaning.
```

---

# 91. Implementation Rule for Coding Agents

When implementing a new capability, a coding agent SHOULD first identify the closest reference pattern in this document.

It MUST NOT copy implementation details blindly.

It SHOULD copy:

```text
architectural shape
ownership boundary
result semantics
Resource/Session use
testing expectations
```

If the proposed capability fits none of the reference patterns without violating the Contract, the agent SHOULD report an architectural question rather than invent a private workaround.

---

# 92. Reference Capability v1 Acceptance Goal

This document succeeds when a new capability author can answer:

```text
What kind of platform object am I building?

What belongs inside the capability?

What belongs in a Procedure?

What belongs in a tool adapter?

Do I need a Resource?

Do I need a Session?

What Result primitives should I return?

How do I represent side effects?

How do I handle uncertainty?

How do I ask for human help?

What tests prove compliance?
```

without requiring knowledge of BoberAgent Core internals.
