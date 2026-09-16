# BoberAgent Core — Project Context

## 1. Purpose

BoberAgent Core is a capability-driven orchestration platform for authorized penetration testing, security labs, CTF environments, and similar controlled assessment workflows.

The project is not intended to be an enumeration wrapper, a collection of pentest scripts, or an LLM that directly executes arbitrary shell commands.

The long-term objective is a system capable of progressing through complete assessment workflows such as:

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
→ extend privileges/access
→ continue from the new state
```

The exact path is not hard-coded. Available capabilities, procedures, accumulated world state, knowledge, and reasoning determine how far the system can progress.

The system must remain extensible: its effective competence should increase primarily by adding capabilities, structured procedures, knowledge and deterministic logic rather than by requiring a fundamentally different architecture.

---

## 2. Core Design Thesis

The central hypothesis of BoberAgent is:

> Model intelligence can be compensated for, to a significant degree, by system intelligence.

The LLM is therefore not the system.

The LLM is one replaceable reasoning component inside a larger deterministic architecture.

BoberAgent should avoid spending model intelligence on problems that can be solved reliably by schemas, parsers, state machines, procedures, policies or ordinary code.

The desired relationship is approximately:

```text
World State       = operational memory
Knowledge System  = accumulated technical knowledge
Workflow Engine   = routines and deterministic procedures
Capability System = ability to act
LLM Reasoner      = interpretation and adaptive problem solving
BoberAgent Core   = the complete system
```

Replacing the model must not require redesigning the platform.

---

## 3. Capability-Driven Architecture

The most important architectural concept is the Capability.

A Capability represents a coherent system-level ability.

Examples:

```text
network.service_discovery
credential.validation
browser.interaction
token.jwt.assessment
secret.hash_recovery
listener.management
session.interaction
runtime.prepare
artifact.repository_acquisition
```

Capabilities are not named after tools.

For example:

```text
network.service_discovery
```

may currently be implemented using Nmap, but Nmap is an implementation dependency rather than part of the capability's identity.

The BoberAgent Core must not depend on how a capability is internally implemented.

A capability implementation may use:

```text
CLI tools
Python code
external APIs
browsers
long-lived processes
runtime environments
LLMs
one tool
multiple tools
```

provided that it complies with the Capability Contract.

---

## 4. Capability Contract

The Capability Contract is treated as a foundational platform contract.

It defines the stable language through which capabilities interact with BoberAgent.

The contract must support radically different execution patterns without special-case Core logic, including:

```text
one-shot processes
long-running processes
local computation
target-facing network interaction
stateful browsers
interactive sessions
listeners
external research
runtime preparation
unknown third-party PoCs
human-assisted execution
target-side state changes
```

The platform meta-model must be more stable than the individual pentest vocabulary built on top of it.

The contract therefore distinguishes concepts including:

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
InteractionRequest
Checkpoint
```

The exact schemas are defined separately in the Capability Contract specification.

---

## 5. Capability and Workflow Are Different Concepts

A Capability answers:

> What can the system do?

A Workflow or Procedure answers:

> When, why, and in what order should capabilities be used?

For example:

```text
network.service_discovery
ad.smb_baseline
ad.ldap_baseline
credential.validation
```

are capabilities.

An Active Directory baseline assessment is a workflow that may orchestrate several capabilities.

A capability implementation may internally use multiple tools, but it must not autonomously expand into unrelated assessment actions.

Strategic sequencing belongs to workflows, deterministic rules, coverage logic, or the reasoner.

---

## 6. World State and Observations

Capabilities never directly mutate World State.

The basic flow is:

```text
Capability
    ↓
CapabilityResult
    ↓
Observation
    ↓
Observation Store
    ↓
State Reducer
    ↓
World State
```

Observations are immutable records of what was observed during execution.

World State is the current materialized operational understanding of the mission.

Conflicting observations must remain available rather than being destructively overwritten.

Raw evidence must remain traceable from normalized state.

The intended provenance chain is:

```text
Artifact / raw evidence
        ↓
Observation
        ↓
World State
        ↓
Finding / reasoning
```

---

## 7. Resources and Sessions

BoberAgent distinguishes runtime infrastructure from active interaction contexts.

A Resource is a platform-managed runtime object with a lifecycle.

Examples:

```text
Python environment
container
listener
Burp project
browser process
temporary workspace
running process
tunnel
```

A Session represents a persistent stateful interaction context.

Examples:

```text
SSH session
WinRM session
reverse shell
authenticated web session
database session
browser context
```

Resources and Sessions are referenced through stable handles.

Capabilities should depend on abstract Session or Resource properties rather than on the mechanism that originally created them.

A post-access capability should therefore be able to consume a suitable remote session without caring whether that session originated from SSH, an exploit, or an incoming reverse shell.

---

## 8. Effects and Access Transitions

Pentest progress cannot be represented only by observations and findings.

Capabilities may deliberately change target state.

Such changes are represented as Effects.

Examples include:

```text
account creation
service configuration change
permission change
new persistence/control mechanism
security-context transition
```

An Effect records what actually changed, separately from the capability's pre-declared possible side effects.

Where appropriate, effects should retain cleanup or reversibility information.

Privilege extension and lateral movement are represented using ordinary capabilities, sessions, effects and World State transitions rather than special Core modes.

The system must be able to reason about changing Access Contexts, for example:

```text
user-level access
        ↓
privilege transition
        ↓
administrative access
```

or:

```text
identity A on host X
        ↓
new access path
        ↓
identity A on host Y
```

The resulting access becomes usable input for subsequent workflows.

---

## 9. Local and Indirect Capabilities

Capabilities do not require a target-facing network action.

The architecture must naturally support operations such as:

```text
hash recovery
JWT analysis
cookie analysis
token generation
file parsing
artifact inspection
PoC preparation
dependency analysis
repository processing
runtime compilation/preparation
```

For example:

```text
captured JWT
+
candidate signing key
        ↓
local JWT assessment
        ↓
key confirmed
        ↓
local token generation
        ↓
new usable credential/token
        ↓
target interaction
        ↓
authenticated session
```

The same Capability Contract must support every stage.

A CapabilityInvocation therefore does not have a universally mandatory target field. Required inputs are defined by the operation-specific input schema.

---

## 10. Unknown PoC Handling

Unknown third-party exploit code is a primary design case rather than an exception.

A typical future workflow is:

```text
technology/version identification
        ↓
CVE research
        ↓
PoC discovery
        ↓
repository acquisition
        ↓
README/source inspection
        ↓
ExecutionPlan
        ↓
isolated runtime preparation
        ↓
execution
        ↓
result interpretation
```

The PoC may initially be completely unknown.

It may require Python, Go, Ruby, compilation, containers, credentials, files, callbacks, listeners or other resources.

The platform must not need prior knowledge of the specific PoC.

The LLM may inspect documentation and source code and produce a structured ExecutionPlan.

Deterministic runtime components validate and execute that plan.

Unknown results are legitimate outcomes and must preserve raw evidence for further interpretation.

---

## 11. Human-in-the-Loop Execution

A running capability may request human assistance without terminating the overall workflow.

Human interaction is represented using structured InteractionRequests.

Example:

```text
RUNNING
   ↓
InteractionRequest
   ↓
WAITING_INPUT
   ↓
human or automated response
   ↓
RUNNING
   ↓
COMPLETED
```

The capability must not implement private blocking console input.

The platform owns interaction routing, persistence, audit and resume behavior.

Capabilities may checkpoint resumable state while waiting for input.

Interaction may request:

```text
confirmation
choice
text input
structured parameters
secret input
artifact input
```

Human assistance and security/policy approval are distinct concepts.

An InteractionRequest asks for help progressing execution.

A Policy Approval asks whether an already-understood action is permitted.

The higher-level workflow does not need to treat human-assisted success differently from autonomous success. Provenance records how the result was achieved.

---

## 12. Capability SDK Boundary

Capability implementations never receive unrestricted BoberAgent Core access.

They execute through a controlled ExecutionContext.

Conceptually the SDK exposes:

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

Capabilities must not receive APIs such as:

```text
world_state.write
database.write
policy.override
mission.modify
scope.modify
registry.modify
```

Core services retain ownership of platform state.

---

## 13. Execution Node

Execution is separated from reasoning and orchestration.

The initial deployment model is:

```text
Windows Host
│
├── BoberAgent Core
├── World State
├── Workflow Engine
├── Knowledge System
├── LLM integration
│
└── Capability Router
        │
        │ transport
        ▼
Kali Hyper-V VM
│
└── BoberAgent Execution Node
    ├── Capability Runtime
    ├── Capability Registry
    ├── Process Manager
    ├── Resource Manager
    ├── Session Manager
    ├── Workspace Manager
    ├── Artifact integration
    └── Policy enforcement
```

MCP may be used as a transport between the Core and Execution Node.

MCP is not the BoberAgent capability architecture and must not define the internal domain model.

Transport mechanisms must remain replaceable.

---

## 14. Knowledge and Reasoning

BoberAgent uses several distinct knowledge layers.

Operational procedures define deterministic or semi-deterministic workflows.

Curated reference documentation provides canonical technical knowledge.

Semantic retrieval supports fuzzy and contextual knowledge access.

The LLM Reasoner handles interpretation, ambiguous decisions and adaptive problem solving.

GraphRAG is not required for the initial architecture.

Runtime World State and general technical knowledge are separate systems and must not be conflated.

---

## 15. Design Stress Tests

The Capability Contract is considered viable only if the same model can naturally represent all of the following without special-case Core hacks:

```text
Nmap service discovery

Stateful Playwright browser automation

Long-running listener followed by an incoming shell

Burp-backed interactive web assessment

Unknown GitHub PoC:
acquire → inspect → prepare → execute → unknown result

Persistent remote-session interaction

Privilege/access transitions and lateral movement

Local hash/JWT/token processing

Human-assisted capability execution
```

If a future capability requires introducing a one-off exception into BoberAgent Core, the first assumption should be that the abstraction requires reconsideration.

---

## 16. Development Strategy

Development is vertical and capability-driven.

The first useful operation may be only:

```text
network.service_discovery
```

but even this first operation should pass through the real architecture:

```text
Mission
→ Capability Invocation
→ Capability Router
→ Execution Node
→ Capability Runtime
→ Tool execution
→ raw Artifact
→ normalization
→ Observation
→ CapabilityResult
→ Observation Store
→ State Reducer
→ World State
```

The first implementation will therefore appear architecturally expensive relative to the simple task it performs.

This is intentional.

Subsequent capabilities must plug into the same infrastructure rather than building new orchestration paths.

---

## 17. Extensibility Goal

The long-term capability ecosystem should make this possible:

> Given the Capability Contract, SDK, schemas, tests and examples, another developer or coding agent can implement a new capability without needing detailed knowledge of BoberAgent Core internals.

A compliant capability should be discoverable, validated and usable through the platform without manually wiring it into unrelated components.

This is the central extensibility requirement.

---

## 18. Authority of This Document

This document explains the architectural intent and vocabulary of BoberAgent.

It is descriptive, not the complete normative specification.

Normative details belong in the dedicated contract, SDK, World State, workflow, Execution Node and architecture specifications.

If implementation behavior conflicts with those normative specifications, the specifications take precedence.

Architectural decisions that materially change previously accepted behavior must be recorded as ADRs rather than silently introduced during implementation.
