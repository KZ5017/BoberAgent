# BoberAgent Core — World State Model v1

**Status:** Initial normative specification
**Document:** `docs/04_WORLD_STATE_MODEL.md`
**Related:** `01_SYSTEM_ARCHITECTURE.md`, `02_CAPABILITY_CONTRACT.md`, `03_CAPABILITY_SDK.md`

---

# 1. Purpose

This document defines the BoberAgent World State model.

World State is the canonical operational representation of what BoberAgent currently knows about an assessment.

It is not:

* raw tool output;
* capability-local runtime state;
* LLM context;
* general technical knowledge;
* a knowledge graph;
* a filesystem-based report.

World State exists so that every capability, workflow and reasoning component can operate on a shared, normalized representation of the assessment.

---

# 2. Core Principle

The canonical flow is:

```text
Raw Evidence
    ↓
Artifact
    ↓
Observation
    ↓
Observation Store
    ↓
State Reducer
    ↓
World State
    ↓
Workflow / Coverage / Reasoning
```

A capability MUST NOT directly modify World State.

World State MUST be derived from controlled Core-owned state processing.

---

# 3. World State Objectives

World State MUST answer questions such as:

```text
What assets are known?

Which services are currently believed to exist?

What technologies and versions are associated with them?

What identities are known?

Which credentials or secrets are available?

Which credentials have been validated?

What Sessions currently exist?

With what authority?

What access paths have been established?

What vulnerabilities or Findings are known?

What Effects have been introduced?

What capabilities have already been attempted?

What information remains unknown?

What changed during the assessment?
```

These answers must be machine-readable.

---

# 4. Separation of Historical Evidence and Current State

BoberAgent MUST distinguish between:

```text
Observation Store
```

and:

```text
World State
```

The Observation Store is historical and append-oriented.

World State is the current materialized operational interpretation.

Example:

```text
09:00 Observation:
TCP/445 open

09:20 Observation:
TCP/445 filtered
```

Both observations remain stored.

World State may currently represent:

```text
TCP/445 state = uncertain / changed
```

or prefer one observation according to reducer rules.

Historical evidence MUST NOT be destroyed merely because World State changes.

---

# 5. Observation Store

Observations are immutable after creation.

An Observation records:

```text
who/what produced the information;
when it was observed;
what subject it concerns;
what was observed;
confidence;
supporting evidence.
```

Every Observation SHOULD preserve provenance to the CapabilityRun or trusted Core process that produced it.

---

# 6. Observation Structure

Conceptually:

```yaml
observation_id: obs-123

type: network.service.state

subject_ref: service-17

value:
  state: open

confidence: 1.0

observed_at: ...

source:
  run_ref: run-42

evidence_refs:
  - artifact-91
```

Observation types belong to an extensible pentest vocabulary.

The World State architecture MUST NOT depend on a fixed closed list of Observation types.

---

# 7. Observation Immutability

Once persisted, an Observation MUST NOT be modified to reflect later knowledge.

Corrections produce new Observations.

If an original Observation is known to be invalid, it MAY be marked through separate metadata or supersession relationships, but its original content MUST remain auditable.

---

# 8. State Reducer

The State Reducer consumes Observations and other Core-authorized state events and materializes canonical World State.

The reducer owns:

```text
normalization
merging
deduplication
confidence handling
conflict detection
supersession
derived state
lifecycle transitions
```

Individual capabilities MUST NOT implement canonical state-merging rules.

---

# 9. Reducer Determinism

Where possible, State Reducer behavior SHOULD be deterministic.

Given the same ordered inputs and the same reducer version, the same World State SHOULD be reproducible.

This improves:

```text
debugging
testing
audit
replay
migration
```

LLM output MAY contribute Observations or Findings, but canonical merge semantics SHOULD remain deterministic whenever practical.

---

# 10. Provenance

Every important World State fact SHOULD be traceable.

Preferred chain:

```text
World State fact
      ↓
Observation
      ↓
CapabilityRun
      ↓
Artifact / raw evidence
```

Derived state SHOULD retain the Observation references that caused the derivation.

---

# 11. Confidence

Not every fact is equally reliable.

The model SHOULD support confidence.

Example:

```text
TCP/445 open:
confidence = 1.0

Operating system = Windows:
confidence = 0.75

Technology version = 4.2.x:
confidence = 0.45
```

Confidence is not a substitute for provenance.

A high-confidence claim still requires supporting evidence where appropriate.

---

# 12. Contradictory Evidence

World State MUST support contradictory Observations.

Example:

```text
Observation A:
OS family = Windows
confidence = 0.8

Observation B:
OS family = Linux
confidence = 0.6
```

The system MUST NOT arbitrarily delete one observation.

The materialized state MAY represent:

```yaml
os_family:
  status: uncertain
  candidates:
    - value: windows
      confidence: 0.8
    - value: linux
      confidence: 0.6
```

or another reducer-approved equivalent.

---

# 13. Unknown State

Unknown information is first-class.

The platform MUST distinguish:

```text
unknown
```

from:

```text
known absent
```

Example:

```text
SMB signing:
unknown
```

does not mean:

```text
SMB signing:
disabled
```

Coverage calculations depend on this distinction.

---

# 14. Domain Entity Model

World State v1 defines the following primary domain concepts:

```text
Mission

Asset
Host
Application
Service
Technology

Identity
Credential
SecretRef
AccessContext

Observation
Finding
Vulnerability

Artifact
ExploitCandidate
ExecutionPlan

Resource
Session
Process

CapabilityRun
Attempt
Decision

Effect
```

Not every entity must be fully implemented in the first bootstrap milestone.

The schema boundaries SHOULD nevertheless anticipate them.

---

# 15. Entity Identity

Every canonical World State entity MUST have a stable logical identifier.

Examples:

```text
asset-17
service-22
identity-8
credential-19
session-41
```

Physical implementation details MUST NOT serve as canonical identities.

Examples of invalid canonical identity:

```text
/tmp/scan.xml
PID 1293
file descriptor 7
Python object address
```

---

# 16. Asset

Asset represents a scoped assessment object.

An Asset may represent:

```text
host
application
domain
network device
service endpoint
other assessable entity
```

Asset is the broad parent abstraction.

---

# 17. Host

Host represents a compute/network system.

Conceptual fields may include:

```text
host_id
asset_ref

addresses
hostnames
domain membership

os_family
os_version
architecture

reachability
```

Many of these properties are reducer-derived and may carry confidence and provenance.

---

# 18. Address Representation

Addresses SHOULD be separate structured values rather than embedded into arbitrary strings.

Examples:

```text
IPv4
IPv6
hostname
FQDN
```

Multiple addresses MAY belong to one Host.

The system SHOULD support the possibility that several observed addresses later resolve to the same canonical Host.

---

# 19. Application

Application represents an application-level target or service grouping.

Examples:

```text
web application
API
administrative interface
custom network application
```

An Application MAY span one or more Services.

It may have:

```text
URLs
technology stack
authentication mechanisms
sessions
identities
findings
```

---

# 20. Service

Service represents a reachable or locally identified service endpoint.

Conceptually:

```yaml
service_id: service-17

asset_ref: host-5

transport: tcp
port: 445

state: open

service_family: smb
product: ...
version: ...
```

Service identity MUST not be tied solely to one scanner's naming convention.

---

# 21. Technology

Technology represents identified software, framework, platform or component.

Examples:

```text
nginx
Apache
WordPress
Django
Windows Server
OpenSSH
custom application framework
```

Technology identity and version information MAY be uncertain.

Observed version strings SHOULD remain traceable to their source evidence.

---

# 22. Identity

Identity represents a security principal.

Examples:

```text
local account
domain account
service account
application user
database account
machine account
API identity
```

Identity is not equivalent to Credential.

One Identity may have multiple Credentials.

One Credential may potentially apply to multiple candidate Identities until validated.

---

# 23. Credential

Credential represents authentication material and its context.

Credential MUST NOT necessarily contain the plaintext secret itself.

Conceptually:

```yaml
credential_id: credential-12

identity_ref: identity-4

credential_type: password

secret_ref: secret-91

scope:
  domain_ref: ...
  service_family: ...

validation_state: candidate
```

Credential lifecycle may include:

```text
candidate
validated
rejected
expired
unknown
```

---

# 24. SecretRef

Sensitive values belong to the Secret Store.

World State stores:

```text
secret_ref
```

rather than canonical plaintext.

Secret types may include:

```text
password
private key
API token
JWT signing key
session token
hash-derived plaintext
other sensitive material
```

---

# 25. Credential Discovery Flow

Example:

```text
Artifact
contains candidate credential material
        ↓
Capability
extracts or recovers secret
        ↓
Secret Store
        ↓
secret_ref
        ↓
Observation
        ↓
Credential entity created/updated
        ↓
credential.available event
        ↓
Workflow may invoke credential.validation
```

The capability MUST NOT directly insert arbitrary canonical Credential records.

Core state processing owns canonical registration.

---

# 26. AccessContext

AccessContext represents what an Identity can currently do in a particular context.

It is one of the most important World State entities.

Conceptually:

```yaml
access_context_id: access-55

identity_ref: identity-7

asset_ref: host-12

session_ref: session-19

authority:
  authenticated: true
  administrative: false
  system: false

groups:
  - users

privileges:
  - ...

source_refs:
  - observation-88
```

---

# 27. AccessContext Is Contextual

An Identity does not have one universal privilege level.

Example:

```text
userA on workstation:
local administrator

userA on domain controller:
no access

userA in web application:
admin role
```

These are distinct AccessContexts.

---

# 28. Privilege Transition

Vertical privilege extension is represented as a transition:

```text
AccessContext A
     ↓
CapabilityRun
     ↓
Observation / Effect / Session
     ↓
AccessContext B
```

Example:

```text
user
→ administrator
```

or:

```text
service account
→ SYSTEM
```

The previous AccessContext MUST remain historically available.

---

# 29. Horizontal Access Transition

Horizontal movement uses the same primitives.

Example:

```text
AccessContext:
identity A
host X
        ↓
new valid access
        ↓
AccessContext:
identity A
host Y
```

No separate lateral-movement state engine is required.

---

# 30. Session

World State stores canonical Session metadata.

Runtime-specific Session state remains managed by the Execution Node.

Canonical state MAY include:

```text
session_id
session_type
provider
target_ref
identity_ref
access_context_ref
state
created_by_run
created_at
closed_at
```

The World State MUST NOT require serialization of live runtime objects.

---

# 31. Session Lifecycle

Standard logical Session states SHOULD include:

```text
CREATING
ACTIVE
DEGRADED
CLOSED
FAILED
LOST
```

A Session may disappear independently of the Workflow that created it.

Session lifecycle events MUST update World State.

---

# 32. Session Capability Representation

A Session MAY advertise abstract usable operations.

Examples:

```text
command_execute
file_upload
file_download
navigate
HTTP_request
database_query
```

Workflows SHOULD use these abstract properties when selecting applicable capabilities.

---

# 33. Resource

Resources also have canonical metadata in World State or an associated runtime registry.

Examples:

```text
listener
browser process
Burp project
Python environment
container
workspace
tunnel
managed process
```

Resource runtime internals remain outside World State.

---

# 34. Resource Lifecycle

Canonical lifecycle SHOULD support:

```text
CREATING
READY
BUSY
STOPPING
STOPPED
FAILED
EXPIRED
```

Actual lifecycle vocabularies MAY be Resource-type-specific where necessary.

---

# 35. Finding

Finding is an interpreted security-relevant conclusion.

A Finding SHOULD reference supporting Observations or Artifacts.

Conceptually:

```yaml
finding_id: finding-44

type: authentication.jwt_signing_key_compromised

subject_ref: application-4

status: confirmed

severity: high

confidence: 0.99

evidence_refs:
  - obs-71
  - obs-72
```

---

# 36. Finding Lifecycle

Finding status MAY include:

```text
candidate
confirmed
rejected
superseded
resolved
```

A Finding can evolve as additional evidence appears.

Unlike Observation, Finding is interpretive and MAY have lifecycle state.

---

# 37. Vulnerability

A Vulnerability represents a known or candidate weakness associated with a subject.

It MAY correspond to:

```text
CVE
configuration weakness
application flaw
access-control flaw
custom issue
```

Vulnerability is not identical to Finding.

Example:

```text
Vulnerability:
CVE-XXXX-YYYY candidate on product version

Finding:
Target verified vulnerable
```

or:

```text
Finding:
Observed behavior suggests vulnerability

Vulnerability:
mapped later to known CVE
```

---

# 38. ExploitCandidate

ExploitCandidate represents a potential exploit or PoC relevant to a Vulnerability or target condition.

It MAY reference:

```text
source URL
repository Artifact
CVE
technology/version requirements
inspection status
applicability status
ExecutionPlan
```

ExploitCandidate is state about a candidate technique, not executable code itself.

Executable/source material belongs to Artifact.

---

# 39. ExecutionPlan

ExecutionPlan may be represented in World State when generated for dynamic code or unknown PoCs.

It SHOULD record:

```text
source artifact
runtime
dependencies
bindings
expected effects
uncertainties
validation status
approval status
execution status
```

ExecutionPlan lifecycle MUST remain separate from CapabilityRun lifecycle.

---

# 40. Effect

Effect records a state change caused during assessment.

Examples:

```text
account created
service modified
permission changed
file modified
access context changed
persistent runtime object introduced
```

An Effect is not equivalent to an Observation.

Observation:

```text
service now runs as account X
```

Effect:

```text
assessment changed service account to X
```

The first describes target state.

The second records assessment causality.

---

# 41. Effect Lifecycle and Cleanup

Effect SHOULD record when known:

```text
reversible
cleanup required
cleanup completed
cleanup capability
cleanup inputs
```

Example:

```yaml
cleanup:
  required: true
  status: pending
  capability_id: service.configuration.restore
```

This enables mission-level cleanup tracking.

---

# 42. Assessment-Induced State

World State SHOULD distinguish between:

```text
target state discovered
```

and:

```text
target state introduced by the assessment
```

Effect provenance provides this distinction.

This is essential for:

```text
cleanup
reporting
audit
subsequent reasoning
```

---

# 43. Attempt

Attempt records a meaningful test or action already performed.

Examples:

```text
credential validation attempt
payload variant attempt
exploit attempt
login attempt
service probe
```

Attempt exists to support:

```text
duplicate suppression
retry decisions
rate management
reasoning history
```

A CapabilityRun MAY generate one or more Attempts.

---

# 44. Attempt Identity

Attempt identity SHOULD be based on normalized meaningful inputs.

Example:

```text
credential X
against service Y
using protocol Z
```

rather than only:

```text
run-123
```

This enables the system to determine:

> Have we effectively already tested this?

---

# 45. Retry History

Retry-sensitive workflows SHOULD query Attempt history before executing.

Example:

```text
same exploit
same parameters
same target state
already attempted
```

may not justify another run.

But:

```text
same exploit
new parameter
new access context
changed target state
```

may represent a valid new Attempt.

---

# 46. Decision

Decision records meaningful orchestration or reasoning choices.

Examples:

```text
selected capability A instead of B
stopped exploit branch
requested human interaction
selected alternate payload family
classified environment as probable AD
```

Decision records SHOULD include:

```text
decision type
inputs/evidence
chosen outcome
reason/source
timestamp
```

Decisions improve auditability and future debugging.

---

# 47. LLM Decisions

When the LLM materially influences execution, the resulting Decision SHOULD record that source.

Example:

```yaml
source:
  type: llm
  model_ref: ...
```

Full hidden model reasoning MUST NOT be required for system audit.

Instead store concise structured rationale where useful.

---

# 48. State Relationships

World State is relational even if the initial storage engine is SQLite.

Important relationships include:

```text
Host
 └── HAS_SERVICE → Service

Application
 └── USES_TECHNOLOGY → Technology

Identity
 └── HAS_CREDENTIAL → Credential

Credential
 └── REFERENCES_SECRET → SecretRef

Session
 ├── TARGETS → Asset
 ├── USES_IDENTITY → Identity
 └── HAS_ACCESS_CONTEXT → AccessContext

Finding
 └── SUPPORTED_BY → Observation

Observation
 └── DERIVED_FROM → Artifact

CapabilityRun
 └── PRODUCED → Observation / Artifact / Effect

Effect
 └── MODIFIED → Entity
```

The initial implementation MAY use foreign keys and association tables rather than graph storage.

---

# 49. State Graph Semantics

Graph-like relationships MAY be exposed through query APIs even when stored relationally.

BoberAgent MUST NOT require Neo4j or another graph database merely because the domain contains relationships.

Graph storage may be introduced later if justified by query complexity.

---

# 50. Temporal State

Many properties change over time.

World State SHOULD preserve timestamps for:

```text
first observed
last observed
last confirmed
created
changed
closed
expired
```

Temporal semantics are especially relevant to:

```text
sessions
credentials
services
resources
access contexts
effects
```

---

# 51. Current Materialized State

For operational use, consumers SHOULD be able to query a current materialized representation without replaying all observations manually.

Example:

```text
get current known services for asset X
get active sessions
get validated credentials
get current access contexts
get unresolved findings
```

The reducer/persistence layer owns this view.

---

# 52. Historical Queries

The model SHOULD also support historical queries such as:

```text
What did we know before run-200?

Which observation changed this field?

When was this credential first validated?

Which capability caused this access transition?
```

Full event sourcing is not required in v1, but sufficient provenance MUST be retained to answer these questions where practical.

---

# 53. World State Query API

Capabilities access state through the SDK `EntityReader`.

Workflows, Coverage Engine and Reasoner require richer Core-side query interfaces.

Conceptually:

```text
get_asset(...)
get_services(asset_ref)
get_credentials(...)
get_active_sessions(...)
get_access_contexts(...)
get_findings(...)
get_attempt_history(...)
```

Queries SHOULD return typed domain objects.

Direct raw SQL SHOULD remain internal to the state repository implementation.

---

# 54. Capability Applicability

World State exists partly to make capability applicability machine-readable.

Example:

```text
Capability:
credential.validation

requires:
credential candidate
+
compatible known service
```

The router/workflow can derive valid invocations from World State.

Another example:

```text
Capability:
linux.local_baseline

requires:
active session
+
command execution support
+
target OS likely Linux
```

This SHOULD NOT require the capability to rediscover those facts independently.

---

# 55. Workflow Progress

Workflow progress is expressed through state satisfaction, not just executed step count.

Example:

```text
Goal:
obtain administrative access on host X
```

may become satisfied when World State contains:

```text
active AccessContext
asset = X
administrative = true
```

regardless of the exact mechanism that produced it.

This allows workflows to remain capability-implementation independent.

---

# 56. Coverage

Coverage Engine evaluates World State against profile requirements.

Example:

```yaml
profile: active_directory_baseline

required_facts:
  - domain.identity
  - smb.signing
  - ldap.reachability
  - kerberos.reachability
```

Each fact may be:

```text
known
unknown
conflicting
not_applicable
```

Coverage completion MUST NOT simply mean:

```text
capability was executed
```

It means required knowledge is sufficiently represented.

---

# 57. Event-to-State Flow

Core events may trigger State Reducer actions.

Example:

```text
session.created
      ↓
Session registered
      ↓
AccessContext may be derived
      ↓
World State updated
      ↓
workflow reevaluation
```

Another:

```text
credential.available
      ↓
World State updated
      ↓
credential-validation workflow becomes applicable
```

---

# 58. State Change Notifications

When materialized World State meaningfully changes, Core SHOULD emit state-oriented events.

Examples:

```text
state.service.discovered
state.credential.available
state.access_context.created
state.access_context.elevated
state.session.active
state.finding.confirmed
```

These are Core-owned events.

Capabilities MUST NOT impersonate these events directly.

---

# 59. Credential Example

End-to-end:

```text
Artifact contains password/hash/token
          ↓
Capability extracts or recovers material
          ↓
Secret Store
          ↓
secret_ref
          ↓
Observation
          ↓
State Reducer
          ↓
Credential(candidate)
          ↓
credential.available
          ↓
Workflow
          ↓
credential.validation
          ↓
Observation
          ↓
Credential(validated)
```

No capability performs direct Credential DB mutation.

---

# 60. JWT / Cookie Example

World State might contain:

```text
Application
  auth mechanism = JWT

Artifact
  captured JWT

Secret
  candidate signing key
```

Capability:

```text
token.jwt.assessment
```

produces:

```text
Observation:
candidate key validates token signature
```

Reducer may create/update:

```text
Credential/Secret relationship
Application auth-state
Finding
```

A token-generation capability may later create a new Secret-backed Credential.

A target-facing capability may establish a new authenticated Session.

Each transition remains explicit.

---

# 61. Unknown PoC Example

Initial state:

```text
Technology
Vulnerability candidate
ExploitCandidate
repository Artifact
```

Inspection produces:

```text
ExecutionPlan
```

Execution may produce:

```text
Observation
Artifact
Effect
Session
UNKNOWN outcome
```

If a Session appears:

```text
session.created
      ↓
Session
      ↓
AccessContext
      ↓
new post-access capabilities become applicable
```

The workflow does not need special knowledge of that specific PoC.

---

# 62. Human-Assisted Execution Example

A CapabilityRun enters:

```text
WAITING_INPUT
```

Checkpoint and InteractionRequest are persisted.

World State does not treat this as security progress by itself.

After human input:

```text
CapabilityRun resumes
      ↓
result produced
      ↓
normal Observation / Effect / Session flow
```

Whether the final result was autonomous or human-assisted MUST NOT alter the semantics of the resulting World State.

Provenance SHOULD retain assistance metadata.

---

# 63. Browser Runtime Example

The browser Session may internally hold:

```text
cookies
localStorage
page handles
tabs
navigation stack
```

These are runtime state.

World State stores only assessment-relevant facts such as:

```text
authenticated session exists
identity inferred/verified
token captured
application endpoint discovered
technology observed
```

The platform MUST NOT mirror browser internals indiscriminately.

---

# 64. Service Discovery Reference Flow

```text
network.service_discovery
       ↓
Nmap XML Artifact
       ↓
Observations
       ↓
State Reducer
       ↓
Host
Service 22/tcp
Service 80/tcp
Service 445/tcp
```

Environment classification may then derive:

```text
possible Windows environment
possible Active Directory environment
```

without Nmap itself controlling workflow.

---

# 65. Access Transition Reference Flow

Initial:

```text
Session-1
AccessContext:
  identity = userA
  host = X
  administrative = false
```

Capability execution produces:

```text
Effect
Observation
Session-2
```

Reducer derives:

```text
Session-2
AccessContext:
  identity = admin-like identity
  host = X
  administrative = true
```

Then:

```text
state.access_context.elevated
```

may trigger reevaluation of applicable post-access procedures.

---

# 66. Persistence Model

SQLite is the initial canonical state store.

The relational schema SHOULD distinguish at minimum:

```text
entity identity
materialized state
observations
relationships
provenance
runs
attempts
effects
sessions
resources
```

JSON columns MAY be used for extensible typed payloads where appropriate.

Core identity and relationship fields SHOULD remain queryable without parsing arbitrary opaque JSON.

---

# 67. Schema Evolution

World State schema WILL evolve.

Migration support MUST exist from the beginning.

The implementation SHOULD use explicit schema versions and migrations.

Changing Python/Pydantic classes alone is not sufficient database migration strategy.

---

# 68. Domain Vocabulary Evolution

The domain vocabulary must remain extensible.

Example Observation types may grow from:

```text
network.service
```

to:

```text
smb.signing
ldap.bind_behavior
web.jwt.algorithm
linux.kernel.version
```

Adding new vocabulary SHOULD NOT require redesigning the World State meta-model.

---

# 69. Structured Values

Important Observation values SHOULD use structured schemas rather than prose where possible.

Prefer:

```json
{
  "transport": "tcp",
  "port": 445,
  "state": "open"
}
```

over:

```text
"Port 445 seems open."
```

Human-readable descriptions MAY accompany structured data.

---

# 70. Canonicalization

The reducer SHOULD canonicalize equivalent values.

Examples:

```text
Microsoft-DS
microsoft-ds
SMB
```

may map to normalized service concepts while preserving original evidence.

Canonicalization MUST NOT discard raw source representation.

---

# 71. Deduplication

Repeated identical observations SHOULD NOT create uncontrolled World State duplication.

However, repeated evidence may increase confidence or confirm persistence over time.

Observation history MAY contain repeated observations.

Materialized state SHOULD represent them efficiently.

---

# 72. Expiration and Freshness

Some state becomes stale.

Examples:

```text
active Session
temporary credential
service reachability
listener Resource
dynamic token
```

The model SHOULD support freshness/expiration semantics.

Static facts such as:

```text
historical Artifact hash
```

do not expire.

---

# 73. Active vs Historical Objects

Consumers MUST be able to distinguish:

```text
active session
```

from:

```text
historical closed session
```

and:

```text
currently valid credential
```

from:

```text
historically valid credential
```

Objects SHOULD generally remain historically queryable after becoming inactive.

---

# 74. Deletion Policy

Operational history SHOULD rarely be physically deleted during a Mission.

State changes SHOULD normally be represented by lifecycle transitions.

Hard deletion should be reserved for:

```text
explicit retention policy
privacy/security requirement
corrupt temporary objects
administrative maintenance
```

Audit-relevant state should remain traceable.

---

# 75. Secret Redaction

World State serialization for:

```text
logs
LLM context
API responses
reports
```

MUST NOT automatically resolve SecretRefs.

Secret resolution requires explicit authorized access.

The existence of a SecretRef may be visible without exposing its value.

---

# 76. LLM Context Projection

The LLM SHOULD NOT receive the entire raw World State database.

A Context Builder SHOULD select relevant state.

Example:

```text
current objective
relevant assets
relevant services
active sessions
available credentials
recent findings
attempt history
relevant knowledge
```

The projection remains derived from canonical World State.

The LLM does not own state.

---

# 77. Context Builder

A future Core service SHOULD provide task-specific World State projections.

Examples:

```text
AD-assessment context
web-assessment context
post-access context
PoC-evaluation context
```

This reduces:

```text
token usage
irrelevant information
reasoning confusion
```

and limits sensitive-data exposure.

---

# 78. State and Knowledge Separation

World State contains mission-specific operational facts.

Knowledge contains reusable general information.

Example:

World State:

```text
host X has SMB signing required
```

Knowledge:

```text
what SMB signing means
how it affects assessment decisions
```

These systems MUST remain separate.

---

# 79. State and Procedure Separation

World State says:

```text
credential-7 exists
service-22 supports SMB
```

Procedure says:

```text
new credential + SMB service
→ credential validation may be required
```

The procedure must not be embedded as a hidden side effect of state storage.

---

# 80. State and Capability Separation

World State says:

```text
SSH session active
```

Capability says:

```text
session.command_execution is available
```

Workflow decides whether to use it.

No layer should silently assume the responsibilities of another.

---

# 81. Initial State Repository Interfaces

The Core state package SHOULD expose stable repository/service interfaces rather than letting callers use ORM/database objects directly.

Conceptually:

```python
assets.get(...)
assets.find(...)

services.for_asset(...)

credentials.available(...)

sessions.active(...)

access_contexts.for_asset(...)

observations.append(...)
findings.get(...)
attempts.find_equivalent(...)
effects.pending_cleanup(...)
```

Exact APIs are implementation details.

The ownership boundary is normative.

---

# 82. Reducer Registration

State reducers MAY be modular.

Example:

```text
NetworkReducer
IdentityReducer
CredentialReducer
SessionReducer
AccessReducer
FindingReducer
```

Adding support for new Observation families SHOULD preferably require registering/extending reducer logic rather than editing one monolithic reducer.

---

# 83. Reducer Safety

Reducers MUST validate incoming Observation schemas.

Invalid or unknown Observation payloads MUST NOT corrupt materialized state.

They MAY:

```text
reject
quarantine
store as unmaterialized observation
emit diagnostic
```

while preserving evidence.

---

# 84. Unknown Observation Types

A capability may legitimately introduce an Observation type not yet understood by the current reducer.

Such an Observation SHOULD remain stored.

Failure to materialize it MUST NOT automatically invalidate the CapabilityRun.

This allows capability vocabulary to evolve ahead of reducer support when necessary.

---

# 85. Materialization Status

Observation processing SHOULD track materialization state such as:

```text
PENDING
MATERIALIZED
PARTIALLY_MATERIALIZED
UNSUPPORTED
REJECTED
```

This provides auditability and allows future reducer versions to reprocess historical observations.

---

# 86. Replay

The architecture SHOULD permit rebuilding materialized World State from persistent observations and lifecycle records where practical.

This does not require a pure event-sourced architecture.

It does require that reducer inputs and provenance are sufficiently preserved.

---

# 87. Derived Facts

Some facts may be derived entirely by Core.

Example:

```text
ports 88 + 389 + 445 detected
+
domain indicators
        ↓
probable Active Directory environment
```

Derived facts SHOULD be represented with provenance to their source observations.

They SHOULD be distinguishable from directly measured facts.

---

# 88. Reasoning-Derived Facts

LLM-derived hypotheses MUST be distinguishable from deterministic facts.

Example:

```text
Hypothesis:
This application may use framework X.
```

should not silently become:

```text
Technology = framework X confirmed
```

unless evidence supports confirmation.

The state model SHOULD support:

```text
hypothesis
candidate
confirmed
```

semantics where useful.

---

# 89. World State Invariants

The following invariants MUST hold:

```text
Capabilities never directly mutate World State.

Observations are immutable.

Raw evidence remains traceable.

Secrets are referenced, not casually embedded.

Current state does not erase historical evidence.

Runtime handles are not raw runtime objects.

Access authority is contextual.

Negative test results are not execution failures.

Unknown information remains distinguishable from absent information.

Assessment-induced changes are represented as Effects.

World State and general knowledge remain separate.
```

---

# 90. Reference Stress Cases

The World State model MUST naturally support:

```text
network discovery

AD enumeration

web application state

authenticated browser sessions

JWT/cookie analysis

hash recovery

listener → reverse shell

SSH/WinRM sessions

unknown PoC execution

new credentials

vertical privilege extension

horizontal access extension

target-side configuration effects

human-assisted execution
```

None should require a separate state architecture.

---

# 91. World State v1 Acceptance Goal

The model is successful if a Workflow or Reasoner can answer, without parsing raw tool output:

```text
Where are we?

What do we know?

How certain are we?

What evidence supports it?

What access do we currently have?

What credentials or sessions are available?

What has already been tried?

What changed because of us?

What still needs to be learned?

Which capabilities are now applicable?
```

If these answers require direct inspection of arbitrary tool files or capability-specific private state, the World State abstraction is insufficient.
