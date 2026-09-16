# BoberAgent Core — System Architecture

**Status:** Initial normative architecture
**Document:** `docs/01_SYSTEM_ARCHITECTURE.md`
**Related:** `00_PROJECT_CONTEXT.md`, `02_CAPABILITY_CONTRACT.md`

---

## 1. Purpose

This document defines the system architecture of BoberAgent Core.

It describes:

* major platform components;
* ownership boundaries;
* runtime and process boundaries;
* Windows-host and Kali execution-node responsibilities;
* state, event, artifact, resource and session flows;
* capability execution;
* workflow and reasoning integration;
* human-in-the-loop execution;
* knowledge integration;
* persistence and recovery;
* security and policy boundaries.

This document defines architecture.

Detailed Capability semantics are defined in `02_CAPABILITY_CONTRACT.md`.

---

## 2. Architectural Objective

BoberAgent is a capability-driven orchestration platform for authorized penetration testing and controlled security assessment environments.

It must support workflows ranging from simple discovery to multi-stage operations such as:

```text
discover
→ classify
→ enumerate
→ assess
→ research
→ prepare
→ exploit
→ establish access
→ enumerate locally
→ extend access or privileges
→ continue from the new state
```

The architecture must not assume that a capability:

* directly interacts with a target;
* is a command-line tool;
* completes immediately;
* is stateless;
* produces only observations;
* has a known result in advance;
* succeeds without human assistance.

The same architecture must support:

* local computation;
* target-facing network operations;
* long-running processes;
* stateful browsers;
* listeners;
* persistent remote sessions;
* Burp-backed workflows;
* hash or token analysis;
* unknown third-party PoCs;
* privilege and access transitions;
* human-assisted execution.

---

## 3. Architectural Principles

### 3.1 The LLM is not the platform

The LLM is a replaceable reasoning component.

Core system behavior must not depend on one particular model.

Deterministic logic should be used wherever the problem can be reliably solved through:

* schemas;
* parsers;
* state machines;
* policies;
* procedures;
* coverage rules;
* ordinary code.

The LLM is primarily responsible for:

* ambiguity resolution;
* interpretation of unstructured information;
* hypothesis generation;
* adaptive decision-making;
* unknown PoC inspection;
* choosing among non-deterministic alternatives.

---

### 3.2 Capabilities provide action; workflows provide sequencing

A Capability represents a reusable system ability.

A Workflow or Procedure decides when and why capabilities are used.

The Core must not embed tool-specific pentest sequences.

---

### 3.3 State belongs to the Core

Capability implementations must never directly mutate canonical World State.

They return structured evidence and results.

Canonical state is produced by Core-owned state-processing services.

---

### 3.4 Runtime infrastructure is explicit

Long-lived runtime objects must not exist as hidden process-local state.

They are represented through explicit Resources and Sessions with stable handles and lifecycle management.

---

### 3.5 Evidence is preserved

Normalized information must remain traceable to raw evidence.

Raw evidence must survive parser, normalization and reasoning failures.

---

### 3.6 Transport is replaceable

MCP may be used between the Core and remote Execution Nodes, but MCP is not the BoberAgent domain architecture.

Capability semantics must remain transport-independent.

---

## 4. Initial Deployment Topology

The first supported deployment consists of a Windows host and a Kali Linux Hyper-V VM.

```text
┌──────────────────────────────────────────────────────────────┐
│ WINDOWS HOST                                                 │
│                                                              │
│ BoberAgent Core                                              │
│                                                              │
│  Mission Manager                                             │
│  World State                                                 │
│  Observation Store                                           │
│  State Reducer                                               │
│  Capability Registry / Router                                │
│  Workflow / Procedure Engine                                 │
│  Coverage Engine                                             │
│  Event Bus                                                   │
│  Interaction Router                                          │
│  Policy / Approval Engine                                    │
│  Secret Store                                                │
│  Artifact Catalog                                            │
│  Knowledge System                                            │
│  LLM Orchestrator                                            │
│  API / CLI                                                   │
│                                                              │
│                 Capability Transport                         │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           │ MCP initially
                           │
┌──────────────────────────▼───────────────────────────────────┐
│ KALI EXECUTION NODE                                          │
│                                                              │
│ BoberAgent Execution Node                                    │
│                                                              │
│  Transport Endpoint                                          │
│  Capability Runtime                                          │
│  Capability Registry                                         │
│  Process Manager                                             │
│  Resource Manager                                            │
│  Session Manager                                             │
│  Workspace Manager                                           │
│  Artifact Client                                             │
│  Secret Resolver                                             │
│  Local Policy Enforcement                                    │
│                                                              │
│  Capability Implementations                                  │
│        │                                                     │
│        ├── nmap                                              │
│        ├── NetExec                                           │
│        ├── Playwright                                        │
│        ├── Burp integration                                  │
│        ├── hashcat / John                                    │
│        ├── git / compilers / interpreters                    │
│        └── future tools                                      │
└──────────────────────────────────────────────────────────────┘
```

Additional execution nodes may be added later without changing the fundamental architecture.

---

# 5. BoberAgent Core

## 5.1 Mission Manager

The Mission Manager owns assessment-level context.

A Mission includes at minimum:

* mission identity;
* lifecycle state;
* scope;
* objectives;
* configured policies;
* references to runtime state and artifacts.

Capabilities may read relevant Mission context but may not modify the Mission directly.

---

## 5.2 Scope Manager

Scope is a first-class security boundary.

Scope may contain:

* network ranges;
* individual hosts;
* applications;
* domains;
* explicit exclusions;
* optional constraints.

Scope validation occurs at multiple layers.

At minimum:

```text
Core validation
      +
Execution Node validation
```

A capability implementation must not be able to expand assessment scope.

---

## 5.3 Observation Store

The Observation Store contains immutable observations produced by capability executions and other trusted system processes.

Observations are historical evidence.

They are never destructively overwritten when later evidence disagrees with them.

---

## 5.4 State Reducer

The State Reducer converts accumulated observations into materialized World State.

```text
Observations
     ↓
State Reducer
     ↓
World State
```

The reducer owns:

* merging;
* deduplication;
* confidence handling;
* contradiction handling;
* domain-state derivation.

A capability cannot invoke arbitrary World State writes.

---

## 5.5 World State

World State represents the current operational model of the assessment.

Initial domain entities are expected to include:

```text
Mission
Asset
Host
Application
Service
Technology
Identity
Credential
AccessContext

Observation
Finding
Vulnerability

Artifact
ExploitCandidate
ExecutionPlan

Resource
Session
Listener
RuntimeEnvironment
Process

CapabilityRun
Attempt
Decision
Effect
```

This vocabulary is expected to evolve.

The platform meta-model must remain more stable than the pentest-specific ontology.

---

## 5.6 Access Context

AccessContext represents usable authority within a specific context.

Examples:

```text
user A on host X
local administrator on host X
SYSTEM on host X
authenticated user B in application Y
database identity C
```

A Session may reference an AccessContext.

Privilege escalation and lateral movement are modeled as state transitions between AccessContexts rather than as special platform modes.

Example:

```text
Session A
AccessContext:
  host = X
  identity = user
  administrative = false

        ↓ capability + verified effect

Session B
AccessContext:
  host = X
  identity = administrator
  administrative = true
```

Horizontal transitions use the same model across assets or identities.

---

## 5.7 Capability Registry

The Capability Registry stores discovered Capability Definitions.

Capabilities are dynamically registered from execution nodes and potentially local providers.

The Core must not rely on a hard-coded capability list.

The registry records:

* capability ID;
* contract version;
* implementation version;
* provider/execution node;
* operations;
* declared dependencies;
* execution characteristics;
* risk and side-effect declarations.

---

## 5.8 Capability Router

The Capability Router resolves a requested capability operation to an appropriate provider.

Routing may consider:

* capability availability;
* execution environment;
* dependency availability;
* resource requirements;
* scope;
* policy;
* node health;
* active Resources or Sessions.

Tool names must not be used as the primary routing abstraction.

---

## 5.9 Workflow / Procedure Engine

The Workflow Engine orchestrates capabilities.

It owns:

* sequencing;
* branching;
* retry decisions;
* coverage logic integration;
* prerequisite checking;
* waiting for asynchronous conditions;
* reacting to new World State.

A Workflow describes what should happen.

A Capability describes what can be done.

These concepts must remain separate.

---

## 5.10 Coverage Engine

The Coverage Engine determines whether required assessment facts are known.

For example, an Active Directory baseline profile may require knowledge of:

* domain identity;
* host identity;
* SMB state;
* LDAP state;
* Kerberos state;
* DNS state;
* credential-validation results where credentials exist.

Coverage must not depend on the LLM remembering what has or has not been tested.

---

## 5.11 Event Bus

BoberAgent uses event-driven coordination.

Example events:

```text
capability.run.created
capability.run.started
capability.run.completed
capability.run.failed

observation.created
finding.created
artifact.created
effect.recorded

resource.ready
resource.failed
resource.closed

session.created
session.closed

credential.available
access_context.changed

interaction.requested
interaction.resolved
```

The initial implementation may use an in-process asynchronous event dispatcher.

An external message broker is not required initially.

The event schema must nevertheless be transportable and persistable.

---

## 5.12 Interaction Router

The Interaction Router owns human-in-the-loop execution.

Capabilities must not directly read from stdin or depend on a specific UI.

A capability creates an InteractionRequest.

```text
RUNNING
   ↓
InteractionRequest
   ↓
WAITING_INPUT
   ↓
Interaction Router
   ├── Human UI / CLI
   └── optionally automated responder / LLM
   ↓
InteractionResponse
   ↓
RUNNING
```

Supported interaction classes should include:

* confirmation;
* selection;
* text input;
* structured form;
* secret input;
* artifact input.

Interaction and policy approval are distinct mechanisms.

---

## 5.13 Policy / Approval Engine

The Policy Engine decides whether actions are permitted.

Capability Definitions describe possible effects before execution.

Policy considers at minimum:

* mission scope;
* action risk;
* target interaction;
* credential usage;
* local modification;
* target modification;
* possible remote code execution;
* unknown side effects;
* configured automation level.

The Policy Engine, not individual capabilities, owns approval requirements.

---

## 5.14 Secret Store

Sensitive values must not be spread through World State, logs or ordinary artifacts.

Examples:

* passwords;
* private keys;
* recovered plaintext;
* API keys;
* signing secrets;
* authentication tokens.

Canonical state stores references such as:

```text
secret_ref
credential_ref
```

The Secret Store owns sensitive values.

Capability implementations access secrets only through the controlled SDK.

Capabilities that legitimately discover or generate secret material may store it through the Secret service and receive a `secret_ref`.

Plain secret material must not be returned in ordinary CapabilityResult fields.

---

## 5.15 Artifact Store and Artifact Catalog

Raw evidence is stored outside canonical World State.

Initial implementation:

```text
filesystem content storage
+
SQLite metadata/catalog
```

Artifacts receive stable logical IDs.

Physical file paths are implementation details.

Artifacts may contain:

* tool output;
* XML;
* JSON;
* HTTP messages;
* screenshots;
* source repositories;
* PoCs;
* downloaded files;
* command output;
* packet captures;
* generated reports.

Artifacts retain:

* provenance;
* hashes;
* MIME/type metadata;
* producing run;
* timestamps.

---

# 6. Knowledge System

The initial knowledge architecture contains four layers.

```text
Procedure Registry
Curated Documentation
Semantic Retrieval
LLM Reasoner
```

GraphRAG is not part of the initial architecture.

---

## 6.1 Procedure Registry

Contains operationally authoritative structured procedures.

Procedures may describe:

```text
goal
preconditions
required observations
capabilities
decision branches
failure handling
completion criteria
```

Procedures are not fuzzy knowledge.

---

## 6.2 Curated Documentation

Canonical technical knowledge is stored as deliberately maintained documentation.

Duplication should be minimized.

One canonical source should be preferred for each concept.

---

## 6.3 Semantic Retrieval

Semantic retrieval supports contextual/fuzzy discovery of relevant technical knowledge.

The retrieval backend must be replaceable.

The initial implementation must expose a stable retrieval service rather than embedding vector-store assumptions into reasoning logic.

---

## 6.4 LLM Orchestrator

The LLM Orchestrator supplies:

* reasoning;
* unstructured interpretation;
* hypothesis generation;
* knowledge-assisted decision-making;
* unknown tool-output interpretation;
* PoC inspection;
* ExecutionPlan generation.

The LLM does not receive unrestricted execution access.

It proposes actions through structured platform mechanisms.

---

# 7. Execution Node Architecture

The Execution Node is more than an MCP server.

It is a managed capability runtime.

```text
Execution Node
│
├── Transport Endpoint
├── Capability Runtime
├── Capability Registry
├── Process Manager
├── Resource Manager
├── Session Manager
├── Workspace Manager
├── Artifact Client
├── Secret Resolver
└── Policy Enforcement
```

---

## 7.1 Capability Runtime

The Capability Runtime:

1. receives a validated invocation;
2. validates local capability availability;
3. validates operation schema;
4. revalidates scope;
5. enforces local policy constraints;
6. resolves required references;
7. checks dependencies;
8. constructs ExecutionContext;
9. executes the implementation;
10. validates returned results;
11. emits lifecycle events;
12. returns the result to Core.

---

## 7.2 Process Manager

Capability implementations should not directly launch arbitrary subprocesses.

The Process Manager provides managed process execution.

It records:

* executable/tool identity;
* arguments where safe;
* run ownership;
* start/end time;
* exit status;
* stdout/stderr artifacts;
* cancellation;
* timeout;
* resource state.

Two primary execution paths are expected:

```text
managed known-tool execution
planned arbitrary execution
```

Unknown PoCs use validated ExecutionPlans rather than direct arbitrary LLM shell execution.

---

## 7.3 Resource Manager

The Resource Manager owns long-lived runtime infrastructure.

Examples:

```text
browser process
listener
Python environment
container
Burp project
workspace
tunnel
long-running managed process
```

Resources have:

* stable handles;
* lifecycle state;
* provider identity;
* ownership;
* access mode;
* lease state;
* expiration/cleanup behavior.

---

## 7.4 Session Manager

The Session Manager owns persistent interactive contexts.

Examples:

```text
browser session
SSH
WinRM
reverse shell
database connection
authenticated web context
```

Session internals are implemented through session drivers.

Example:

```text
Session domain object
       ↓
RemoteShellSessionDriver
       ↓
actual Penelope connection
```

Capabilities operate through the abstract Session API whenever possible.

---

## 7.5 Workspace Manager

Capabilities must use managed workspaces for temporary execution state.

Especially relevant to:

* repository acquisition;
* PoC inspection;
* compilation;
* dependency installation;
* virtual environments;
* generated payload material.

A workspace has a logical handle.

Physical paths are not platform identities.

---

# 8. Persistence

The initial canonical runtime database is SQLite.

Reasons:

* local deployment;
* transactional behavior;
* low operational overhead;
* easy inspection;
* Python compatibility.

SQLite stores metadata and structured runtime state.

Large/raw artifacts remain in the Artifact Store.

The persistence abstraction must permit migration to another database later without changing the Capability Contract.

---

# 9. Asynchronous Execution

Capability execution is asynchronous by design.

The architecture must support:

* long scans;
* cracking tasks;
* browsers;
* listeners;
* waiting sessions;
* human interaction;
* external research;
* resumable workflows.

No architecture layer may assume:

```text
request → immediate response → finished
```

CapabilityRun lifecycle and events are authoritative.

---

# 10. Checkpoint and Recovery

A capability entering a durable waiting state must be resumable without relying on an in-memory Python call stack.

Examples:

```text
WAITING_INPUT
WAITING_RESOURCE
PAUSED
```

A resumable run stores an explicit Checkpoint describing sufficient continuation state.

Example:

```text
phase
attempt history
artifact references
resource/session references
expected response
next logical step
```

The implementation may later reconstruct execution from this checkpoint.

---

# 11. Human-Assisted Execution

Human assistance must not terminate a workflow branch merely because automation has reached uncertainty.

Example:

```text
PoC execution
   ↓
known payload variants fail
   ↓
InteractionRequest
   ↓
human provides parameter or modified artifact
   ↓
Capability resumes
   ↓
Session established
   ↓
normal workflow continues
```

Higher-level workflows consume the resulting state.

They need not treat human-assisted success as a separate success type.

The audit trail must preserve that human assistance occurred.

---

# 12. Target-Side Effects

Capabilities that may modify target state must declare possible side effects before execution.

Actual changes are represented through Effect records.

Examples:

```text
account creation
group membership modification
service configuration change
file modification
permission change
security-context transition
```

Effect records should preserve cleanup/reversibility metadata when available.

Mission cleanup procedures can later operate from recorded Effects.

---

# 13. Unknown PoC Architecture

Unknown PoCs are treated as arbitrary acquired artifacts.

Typical flow:

```text
Artifact acquisition
        ↓
PoC inspection
        ↓
ExecutionPlan
        ↓
Plan validation
        ↓
Policy evaluation
        ↓
Runtime preparation
        ↓
Managed execution
        ↓
Artifact / Observation / Effect / Session / Unknown result
```

The platform must allow the result to remain unknown.

Unknown output is preserved and may be routed to an interpreter or human interaction.

---

# 14. Runtime vs World State

Runtime state and World State must remain distinct.

For example:

Browser runtime may internally contain:

```text
cookies
localStorage
navigation stack
JavaScript state
open tabs
```

These belong to the browser Session unless they are relevant to the assessment.

Relevant facts are emitted as Observations.

The Core must not attempt to mirror every runtime detail into World State.

---

# 15. Failure Semantics

The architecture distinguishes:

```text
execution failure
```

from:

```text
successful execution with negative assessment result
```

Example:

```text
PoC executed successfully.
Target appears not vulnerable.
```

means:

```text
CapabilityRun = COMPLETED
Outcome = TARGET_NOT_VULNERABLE
```

not:

```text
CapabilityRun = FAILED
```

Failure indicates the capability could not correctly complete its requested operation.

---

# 16. Initial Repository Boundaries

The intended monorepo boundaries are:

```text
BoberAgent/
│
├── docs/
├── contracts/
│
├── core/
│   ├── missions/
│   ├── state/
│   ├── capabilities/
│   ├── workflows/
│   ├── policy/
│   ├── events/
│   ├── interactions/
│   ├── artifacts/
│   ├── secrets/
│   ├── knowledge/
│   └── llm/
│
├── execution_node/
│   ├── runtime/
│   ├── processes/
│   ├── resources/
│   ├── sessions/
│   ├── workspaces/
│   ├── transport/
│   └── policy/
│
├── sdk/
├── capabilities/
├── knowledge/
└── tests/
```

Exact Python package names may evolve.

The architectural boundaries must not.

---

# 17. Initial Bootstrap Path

The first end-to-end vertical slice is:

```text
network.service_discovery
```

It must nevertheless use the real architecture.

Required path:

```text
Mission
→ Invocation
→ Capability Registry
→ Capability Router
→ Transport
→ Execution Node
→ Capability Runtime
→ Process Manager
→ Nmap
→ raw Artifact
→ deterministic adapter
→ Observation
→ CapabilityResult
→ Observation Store
→ State Reducer
→ World State
```

The first implementation is intentionally infrastructure-heavy compared with the simple operation being performed.

No direct shortcut from Core to Nmap is permitted.

---

# 18. Architectural Acceptance Cases

The architecture is considered viable only while the same fundamental model naturally supports:

1. Nmap service discovery.
2. Stateful Playwright browser interaction.
3. Long-running listener followed by incoming shell.
4. Burp-backed interactive web assessment.
5. Unknown third-party PoC acquisition, inspection and execution.
6. Persistent remote-session interaction.
7. Vertical and horizontal access transitions.
8. Local hash, cookie and JWT processing.
9. Human-assisted execution and resume.

New use cases should first be expressed through existing primitives.

A Core-specific exception should be introduced only when the existing abstraction is genuinely insufficient.

---

# 19. Non-Goals

The initial architecture does not require:

* distributed message brokers;
* Kubernetes;
* microservices for every component;
* GraphRAG;
* multi-node scheduling sophistication;
* arbitrary third-party untrusted plugin execution;
* full autonomous exploitation coverage.

These may be added when justified by actual requirements.

---

# 20. Architectural Change Rule

Material changes to these boundaries must not be introduced silently during implementation.

If implementation reveals that this architecture prevents a necessary capability:

1. document the conflict;
2. determine whether the problem is implementation-specific or architectural;
3. create an ADR for the proposed architectural change;
4. update normative specifications;
5. only then implement the change.

Implementation convenience is not sufficient justification for violating the architecture.
