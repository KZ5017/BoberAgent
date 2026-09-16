# BoberAgent Core — Bootstrap Implementation Plan v1

**Status:** Initial implementation plan
**Document:** `docs/09_BOOTSTRAP_PLAN.md`
**Related:** `00_PROJECT_CONTEXT.md` through `08_REFERENCE_CAPABILITIES.md`

---

# 1. Purpose

This document defines the initial implementation sequence for BoberAgent Core.

It converts the architecture into an ordered development plan with explicit acceptance criteria.

The objective is NOT to implement the entire long-term BoberAgent feature set.

The objective is to build the smallest real vertical slice that proves the architecture.

The first operational flow is:

```text
Mission
→ Asset
→ Goal
→ Workflow
→ CapabilityInvocation
→ Capability Router
→ Transport
→ Kali Execution Node
→ Capability Runtime
→ network.service_discovery
→ Nmap
→ raw Artifact
→ Observation
→ Core ingestion
→ State Reducer
→ World State
→ Goal satisfied
```

Every architectural layer in this path must be real.

No direct Core → Nmap shortcut is permitted.

---

# 2. Bootstrap Philosophy

The initial implementation deliberately prioritizes architecture over feature breadth.

The first useful system may only perform reliable network service discovery.

That is acceptable.

The bootstrap is successful if the second, third and tenth Capability can later be added without redesigning the platform.

---

# 3. Implementation Rules

During bootstrap:

```text
DO build:
- real contracts
- real persistence
- real SDK boundary
- real Execution Node
- real transport abstraction
- real capability package
- real Artifact handling
- real Observation ingestion
- real State Reducer
- real Workflow state

DO NOT yet build:
- full web UI
- full autonomous exploitation
- GraphRAG
- distributed message broker
- Kubernetes
- advanced multi-node scheduling
- full Burp integration
- production privilege-escalation library
- arbitrary third-party plugin marketplace
```

---

# 4. Architecture Before Convenience

The following shortcuts are forbidden even during bootstrap:

```text
Core directly executing Nmap

Capability writing SQLite World State directly

Capability importing Core internals

Execution Node exposing unrestricted shell as its main API

Tool output becoming World State without normalization

MCP types leaking into Capability Contract

temporary filesystem paths becoming durable identities

hard-coded one-off orchestration inside CLI code
```

If the real architecture makes the first Nmap execution more complicated than a script, that is intentional.

---

# 5. Technology Baseline

Initial implementation target:

```text
Python >= 3.12
Pydantic v2
asyncio-compatible async architecture

SQLite
SQLAlchemy-style repository abstraction
explicit schema migrations

pytest
Ruff
static type checking

structured logging
```

Exact dependency versions must be pinned when implementation begins.

The implementation should prefer maintained libraries over custom infrastructure where they do not violate the architecture.

---

# 6. Repository Layout

Initial monorepo:

```text
BoberAgent/
│
├── AGENTS.md
├── README.md
├── pyproject.toml
├── uv.lock / equivalent lock file
│
├── docs/
│   ├── 00_PROJECT_CONTEXT.md
│   ├── 01_SYSTEM_ARCHITECTURE.md
│   ├── 02_CAPABILITY_CONTRACT.md
│   ├── 03_CAPABILITY_SDK.md
│   ├── 04_WORLD_STATE_MODEL.md
│   ├── 05_WORKFLOW_AND_REASONING.md
│   ├── 06_KNOWLEDGE_SYSTEM.md
│   ├── 07_EXECUTION_NODE.md
│   ├── 08_REFERENCE_CAPABILITIES.md
│   ├── 09_BOOTSTRAP_PLAN.md
│   └── adr/
│
├── packages/
│   ├── contracts/
│   ├── sdk/
│   ├── core/
│   └── execution-node/
│
├── capabilities/
│   └── network-service-discovery/
│
├── knowledge/
│   ├── procedures/
│   └── reference/
│
├── tests/
│   ├── architecture/
│   ├── integration/
│   └── end_to_end/
│
└── scripts/
```

A Python workspace/monorepo tool MAY manage these packages.

The packages MUST remain logically independent.

---

# 7. Package Dependency Direction

The dependency graph is intentionally restrictive.

```text
contracts
   ↑
   ├──────── sdk
   │          ↑
   │          │
   │      capabilities
   │
   ├──────── core
   │
   └──────── execution-node
                ↑
                │
               sdk
```

More explicitly:

```text
contracts:
    imports no Core/Execution Node/Capability implementation

sdk:
    may import contracts
    MUST NOT import core
    MUST NOT import execution-node

capability implementation:
    may import sdk
    may import its own adapters
    MUST NOT import core internals
    MUST NOT import execution-node internals

core:
    may import contracts
    MUST NOT import capability implementation modules

execution-node:
    may import contracts + sdk
    dynamically loads capabilities
```

Core and Execution Node communicate through transport contracts.

---

# 8. Architecture Dependency Tests

Automated tests SHOULD enforce package boundaries.

Examples:

```text
SDK must not import boberagent_core

Capability must not import boberagent_core

Capability must not import execution_node internals

Core must not import Nmap adapter

Contracts must remain infrastructure-independent
```

This prevents accidental architectural erosion.

---

# 9. Milestone 0 — Repository Foundation

## Objective

Create the development environment and architectural guardrails before implementing behavior.

---

## 9.1 Deliverables

Create:

```text
repository structure

Python workspace configuration

package skeletons

test configuration

lint/type-check configuration

logging baseline

docs/

ADR directory
```

Add all approved architecture documents.

---

## 9.2 AGENTS.md

Before implementation, root `AGENTS.md` MUST instruct coding agents to:

```text
read Project Context

read relevant normative specifications

treat Capability Contract as authoritative

not introduce undocumented architecture shortcuts

report architecture/spec conflicts

run tests before declaring completion

preserve package dependency direction
```

The exact AGENTS document should be written before substantial implementation.

---

## 9.3 CI/Quality Commands

The project SHOULD establish canonical commands such as:

```text
lint
typecheck
test
test-contracts
test-integration
```

Exact command syntax may depend on chosen tooling.

---

## 9.4 Acceptance Criteria

Milestone 0 is complete when:

```text
repository installs into clean Python environment

all packages import independently

empty test suite executes successfully

lint passes

type checking executes

architecture documents are present

package-boundary tests exist
```

No pentest tool needs to run yet.

---

# 10. Milestone 1 — Contract Models

## Objective

Implement the machine-readable platform language defined by `02_CAPABILITY_CONTRACT.md`.

This milestone contains no execution logic.

---

# 11. Contract Package

Recommended package:

```text
packages/contracts/
└── src/boberagent_contracts/
    ├── version.py
    ├── enums.py
    ├── refs.py
    │
    ├── capability.py
    ├── invocation.py
    ├── run.py
    ├── result.py
    │
    ├── observation.py
    ├── finding.py
    ├── artifact.py
    ├── effect.py
    ├── diagnostic.py
    │
    ├── resource.py
    ├── session.py
    │
    ├── event.py
    ├── interaction.py
    ├── checkpoint.py
    └── execution_plan.py
```

---

# 12. Strong Reference Types

Do not use arbitrary strings everywhere.

Create typed logical references such as:

```text
MissionRef
AssetRef
ArtifactRef
SecretRef
CredentialRef
ResourceRef
SessionRef
CapabilityRunRef
```

Their serialized form may remain strings.

Their Python representation should prevent accidental cross-type misuse where practical.

---

# 13. Required Initial Contract Objects

Implement at minimum:

```text
CapabilityDefinition
OperationDefinition

CapabilityInvocation
CapabilityRun
CapabilityResult
CapabilityOutcome

Observation
Finding
ArtifactDescriptor
Effect
Diagnostic

ResourceDescriptor
SessionDescriptor

Event

InteractionRequest
InteractionResponse

Checkpoint

ExecutionPlan
```

Not all must be functionally used in the first vertical slice.

They establish Contract v1.

---

# 14. Contract Serialization

Every Contract object MUST support:

```text
validation
JSON serialization
JSON deserialization
schema generation
```

Transport-specific representation must not be embedded in the model.

---

# 15. Contract Tests

Tests MUST verify:

```text
valid objects accepted

invalid references rejected

invalid lifecycle values rejected

terminal Run transitions represented correctly

CapabilityResult distinguishes status/outcome

Secret plaintext is not a normal Result field

InteractionRequest schema validates

unknown outcomes serialize correctly
```

---

# 16. JSON Schemas

Generate/export JSON Schemas for externally exchanged Contract objects.

Schemas SHOULD be versioned.

Generated schemas are derived artifacts.

Pydantic models remain the initial implementation source.

---

# 17. Milestone 1 Acceptance

Complete when:

```text
all Contract objects validate

round-trip serialization works

JSON schemas generate reproducibly

no infrastructure dependencies exist in contracts package

contract test suite passes
```

---

# 18. Milestone 2 — Core Persistence Foundation

## Objective

Create canonical Core persistence before tool execution exists.

Use SQLite initially.

---

# 19. Initial Core Database

Only implement entities required by the first vertical slice plus architecture-critical lifecycle state.

Required tables/entities:

```text
missions
assets

capability_runs

artifacts
observations

services

workflow_runs
goals

events / event delivery metadata where required
```

Additional future tables may be represented in code models but do not need complete operational implementation yet.

---

# 20. Repository Pattern

Business logic MUST use repository/service interfaces.

Avoid direct SQL throughout orchestration code.

Example conceptual services:

```text
MissionRepository
AssetRepository
RunRepository
ObservationRepository
ArtifactRepository
ServiceRepository
WorkflowRepository
GoalRepository
```

---

# 21. Database Migrations

Migration infrastructure MUST exist before schema growth begins.

Rules:

```text
database schema changes require migrations

application startup does not silently destroy/recreate DB

test databases may be ephemeral
```

---

# 22. Observation Store

Implement append-only Observation persistence.

Required:

```text
observation ID
type
subject_ref
value
confidence
timestamp
run provenance
Artifact evidence refs
materialization status
```

Observation update APIs SHOULD NOT exist for ordinary consumers.

---

# 23. Minimal State Reducer

Implement only enough reducer behavior for:

```text
network.service
```

Observations.

Example:

```text
Observation:
asset-1 TCP/445 OPEN

        ↓

Service:
asset-1
tcp
445
OPEN
```

The reducer MUST retain Observation provenance.

---

# 24. Reducer Idempotency

Processing the same Observation twice MUST NOT duplicate materialized state.

Repeated equivalent Observations may update freshness/provenance according to reducer rules.

---

# 25. Core Persistence Acceptance

Complete when tests demonstrate:

```text
Mission creation

Asset creation

Observation append

network.service Observation materializes Service

same Observation replay is safe

database survives Core restart

materialized Service can be queried without parsing Observation payload manually
```

---

# 26. Milestone 3 — Capability SDK

## Objective

Implement the programming interface defined in `03_CAPABILITY_SDK.md`.

No real network capability is required yet.

---

# 27. SDK Interfaces

Implement protocol/abstract interfaces for:

```text
ExecutionContext

ScopeService
EntityReader

ArtifactService
WorkspaceService
ProcessService
ResourceService
SessionService
SecretService

InteractionService
CheckpointService

EventService
CancellationService
ClockService
CapabilityLogger
```

Not every service requires full production backend yet.

---

# 28. Capability Base Interface

Provide standard implementation interface.

Conceptually:

```python
class Capability(ABC):

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        ...
```

Capability manifest remains separate.

---

# 29. Fake ExecutionContext

Implement a high-quality test SDK early.

Required fake services:

```text
FakeEntityReader
FakeScopeService
FakeArtifactService
FakeProcessService
FakeWorkspaceService
FakeSecretService
FakeEventService
FakeInteractionService
FakeClock
FakeCancellation
```

This allows capability development without Core or Kali.

---

# 30. SDK Acceptance

Complete when a dummy capability can:

```text
receive validated input

resolve fake Asset

validate fake Scope

execute fake process

create fake Artifact

return Observation

pass Result validation
```

without importing Core or Execution Node.

---

# 31. Milestone 4 — Execution Node Foundation

## Objective

Create the Kali-side runtime independent of the first real Capability.

---

# 32. Required Node Components

Implement initial:

```text
NodeIdentity

NodeConfiguration

RuntimeDatabase

CapabilityLoader
LocalCapabilityRegistry

ToolRegistry
DependencyResolver

CapabilityRuntime
RunRegistry

ProcessManager
WorkspaceManager

ArtifactSpool

EventOutbox
ResultOutbox
```

ResourceManager and SessionManager SHOULD have stable interfaces, even if their first providers come later.

---

# 33. Node Runtime Database

SQLite runtime DB initially stores:

```text
node identity

known CapabilityRuns

run execution state

workspace records

process records

Artifact spool state

pending Results

pending Events

Checkpoints
```

It MUST NOT store canonical World State.

---

# 34. Process Manager v1

Implement:

```text
known executable resolution

async process start

stdout capture

stderr capture

exit code

timeout

cancellation

Run ownership
```

Output MUST support durable files rather than unlimited in-memory buffering.

---

# 35. Workspace Manager v1

Provide:

```text
RUN-scoped workspace creation

safe path generation

ownership metadata

cleanup
```

Physical path is available only node-side.

---

# 36. Artifact Spool v1

Allow creation of Artifact IDs before Core synchronization.

Store:

```text
bytes/file

hash

type

Run provenance

sync state
```

Use globally unique logical IDs.

---

# 37. Node Recovery v1

On restart:

```text
load runtime DB

identify RUNNING Runs

inspect process state where possible

mark unrecoverable state appropriately

retain pending Result/Event/Artifact delivery
```

No automatic blind retry.

---

# 38. Execution Node Acceptance

Complete when:

```text
node starts with persistent identity

dummy capability can be discovered

dummy Invocation executes

process can be launched through ProcessManager

Run state persists

Result persists before delivery

node restart does not duplicate completed Run

Artifact spool survives restart
```

---

# 39. Milestone 5 — Transport Abstraction

## Objective

Connect Core and Execution Node without coupling domain logic to MCP.

---

# 40. Capability Transport Interface

Define transport-independent operations conceptually similar to:

```text
discover_node

list_capabilities

submit_invocation

get_run_status

cancel_run

receive_events

receive_result

synchronize_artifact
```

Exact API shape may evolve.

---

# 41. In-Memory Transport

Implement an in-memory transport first for integration tests.

Purpose:

```text
prove Core ↔ Node protocol semantics

test duplicate delivery

test Event/Result flow

test reconnect logic

without debugging network transport simultaneously
```

This is testing infrastructure, not the final deployment transport.

---

# 42. Delivery Semantics

Assume at-least-once transport.

Tests MUST simulate:

```text
duplicate Invocation

duplicate Event

duplicate Result

lost acknowledgement
```

No duplicate execution/state corruption may occur.

---

# 43. Transport Acceptance

Complete when:

```text
Core discovers fake Execution Node

Capability definitions register

Core submits Invocation

Node executes dummy capability

Result returns

duplicate Invocation does not rerun

duplicate Result does not duplicate ingestion
```

---

# 44. Milestone 6 — Artifact Synchronization

## Objective

Complete the raw-evidence path before introducing Nmap.

---

# 45. Core Artifact Store

Initial implementation:

```text
filesystem content store
+
SQLite Artifact Catalog
```

Catalog contains:

```text
Artifact ID
type
hash
provenance
storage location
created timestamp
sync state
```

---

# 46. Node → Core Artifact Sync

Implement:

```text
LOCAL_ONLY
→ SYNC_PENDING
→ SYNCED
```

Artifacts MUST retain the same logical ID.

Core MUST verify received content hash.

---

# 47. Deduplication

Content-addressed storage MAY deduplicate bytes internally.

Logical Artifact identity and provenance MUST remain preserved even if bytes are deduplicated.

---

# 48. Artifact Acceptance

Complete when:

```text
Node creates Artifact while Core connected

Core receives bytes + metadata

hash verifies

Artifact readable from Core

same Artifact sync replay is idempotent

Node creates Artifact while Core unavailable

Artifact syncs after reconnect
```

---

# 49. Milestone 7 — `network.service_discovery`

## Objective

Implement the first real Capability.

---

# 50. Capability Package

Create:

```text
capabilities/
└── network-service-discovery/
    ├── capability.yaml
    ├── schemas/
    ├── implementation/
    │   ├── capability.py
    │   └── executor.py
    ├── adapters/
    │   └── nmap_xml.py
    ├── tests/
    │   ├── contract/
    │   ├── unit/
    │   ├── integration/
    │   └── fixtures/
    └── README.md
```

---

# 51. Capability Manifest

Declare:

```text
id = network.service_discovery

operation = discover

one-shot

stateless

async

target_network = true

local_compute = true

dependency = nmap

target_state side effect = read/none as appropriate

retry = CONDITIONAL
```

---

# 52. Input Schema

Minimum:

```text
target_ref

scan profile

timeout
```

Do NOT initially expose every Nmap argument.

Capability input is a semantic service-discovery request, not a raw Nmap CLI wrapper.

---

# 53. Scan Profiles

Bootstrap MAY support only:

```text
baseline
```

The implementation decides appropriate Nmap arguments.

Later profiles may include:

```text
fast
full_tcp
version_detection
```

but only when operationally justified.

---

# 54. Execution Flow

Required:

```text
resolve AssetRef
      ↓
validate scope
      ↓
create Workspace
      ↓
run Nmap through ProcessService
      ↓
capture raw XML
      ↓
create Artifact
      ↓
deterministically parse XML
      ↓
create Observations
      ↓
CapabilityResult
```

---

# 55. XML Parser

Parser MUST be independently testable.

It MUST NOT require:

```text
Core
Execution Node
live Nmap
```

Golden fixtures SHOULD cover:

```text
normal host

host down

multiple ports

version information

missing optional fields

malformed XML
```

---

# 56. Parser Failure

If Nmap produced raw evidence but parsing fails:

```text
Artifact retained

Diagnostic emitted

Outcome may be PARTIAL/UNKNOWN

Run is not allowed to erase the evidence
```

---

# 57. Capability Acceptance

Complete when:

```text
Capability package passes contract validation

Nmap dependency is detected

out-of-scope Asset rejected

real Nmap executes through ProcessManager

XML Artifact generated

XML parser creates network.service Observations

no World State code imported

cancellation works

negative/empty scan does not become runtime failure
```

---

# 58. Milestone 8 — Core Capability Registry and Router

## Objective

Allow Core to discover and invoke the real capability without knowing Nmap exists.

---

# 59. Global Capability Registry

Core stores advertised:

```text
Capability ID
operations
contract version
implementation version
Execution Node
availability
dependencies summary
```

---

# 60. Router v1

The first router may be simple.

Given:

```text
network.service_discovery
```

choose an:

```text
AVAILABLE provider
```

that satisfies required execution context.

No advanced node scoring is required.

---

# 61. Router Invariant

Core MUST NOT contain:

```text
if capability == network.service_discovery:
    call Nmap
```

Routing uses Capability metadata/provider registration.

---

# 62. Registry/Router Acceptance

Complete when:

```text
Execution Node advertises network.service_discovery

Core registry records it

Core can resolve provider

removing Nmap makes advertised capability unavailable

Core does not know executable path or Nmap CLI syntax
```

---

# 63. Milestone 9 — Result Ingestion and World State

## Objective

Close the complete execution loop.

---

# 64. Result Ingestion Flow

```text
CapabilityResult
      ↓
validate Contract
      ↓
deduplicate delivery
      ↓
Artifact references reconciled
      ↓
Observations persisted
      ↓
State Reducer
      ↓
Services materialized
      ↓
state-change Events
```

---

# 65. Result Transaction Boundary

Where practical, result metadata ingestion and Observation persistence SHOULD be transactional.

A partial database failure MUST NOT produce silently inconsistent canonical state.

Artifact byte synchronization may remain asynchronous.

---

# 66. Service Reducer

Bootstrap reducer consumes:

```text
network.service
```

Observations and materializes:

```text
Service
```

with:

```text
Asset relation
transport
port
state
service family/name
product/version where available
provenance/freshness
```

---

# 67. Result Ingestion Acceptance

Complete when:

```text
real node Result reaches Core

Observation is persisted once

duplicate Result delivery is safe

Service materializes

World State query returns service

Observation provenance points to Run/Artifact

Core restart preserves state
```

---

# 68. Milestone 10 — Real MCP Transport

## Objective

Replace test-only in-memory transport in deployment with the initial real Windows ↔ Kali transport.

MCP is the initial preferred transport.

---

# 69. MCP Adapter Rules

MCP-specific code MUST remain inside transport adapters.

It MUST NOT redefine:

```text
CapabilityDefinition

Invocation

Result

Observation

Resource

Session
```

Domain objects are serialized through the transport.

---

# 70. Authentication

The Windows Core ↔ Kali Execution Node connection MUST be authenticated.

The bootstrap MAY use a simple preconfigured secure mechanism appropriate to the local controlled environment.

It MUST NOT expose an unauthenticated arbitrary execution endpoint.

---

# 71. Connectivity

The transport MUST support:

```text
node discovery/handshake

capability advertisement

Invocation delivery

Run status

Event delivery

Result delivery

Artifact synchronization

cancellation
```

Human interaction may be added to the same transport path before interactive capabilities are introduced.

---

# 72. Reconnection Test

Test:

```text
Core sends Run

Node begins execution

transport disconnects

Node completes

Result persists locally

transport reconnects

Result delivered once logically

World State materializes once
```

This is a critical acceptance test.

---

# 73. MCP Acceptance

Complete when the real deployment works across:

```text
Windows Core
        ↕
Kali Hyper-V Execution Node
```

without changing Capability or Core domain code.

---

# 74. Milestone 11 — Minimal Workflow Engine

## Objective

Stop manually invoking the Capability and let orchestration request it from a Goal.

---

# 75. Initial Goal Type

Implement:

```text
goal.network_services_discovered
```

for one Asset.

Goal predicate conceptually:

```text
service-discovery coverage for Asset exists
```

The exact completion marker SHOULD avoid requiring that at least one open port exists.

A legitimate result may be:

```text
no discovered open services
```

and still satisfy the discovery Goal.

---

# 76. Initial Procedure

Create:

```text
procedure.network.service_discovery_baseline@1
```

Conceptual logic:

```text
Goal:
service discovery coverage for Asset

if coverage UNKNOWN:
    invoke network.service_discovery

when definitive discovery observation/result exists:
    mark coverage KNOWN

completion:
    Goal SATISFIED
```

No LLM required.

---

# 77. Workflow Persistence

Persist:

```text
WorkflowRun
Goal
active CapabilityRun ref
completion state
Decision
```

Workflow must survive Core restart.

---

# 78. Workflow Events

Flow:

```text
Workflow ACTIVE
      ↓
CapabilityRun submitted
      ↓
WAITING
      ↓
Result/World State update
      ↓
workflow reevaluation
      ↓
Goal SATISFIED
      ↓
Workflow COMPLETED
```

---

# 79. Duplicate Reevaluation

Repeated state-change Events MUST NOT start a second equivalent service-discovery Run once:

```text
one is active
```

or:

```text
Goal already satisfied.
```

---

# 80. Workflow Acceptance

Complete when:

```text
creating Goal automatically starts correct Capability

Workflow persists

Core restart does not lose Goal

duplicate event does not duplicate scan

negative scan can satisfy Goal

service Observations satisfy Goal

Workflow reaches COMPLETED deterministically
```

---

# 81. Milestone 12 — CLI for Bootstrap Operations

## Objective

Provide a thin human-facing control surface without moving business logic into the CLI.

---

# 82. CLI Responsibilities

CLI may support:

```text
mission create

asset add

workflow start

mission status

asset show

services list

runs list

node status
```

Exact commands may evolve.

---

# 83. CLI Boundary

CLI MUST call Core application services.

It MUST NOT:

```text
open Core SQLite directly

call Nmap

contact Execution Node directly

parse capability-specific output
```

---

# 84. Example Bootstrap Flow

Conceptually:

```text
bober mission create lab-test

bober asset add \
    --mission <id> \
    --address 10.10.11.50

bober workflow start \
    --mission <id> \
    --procedure network.service_discovery_baseline \
    --asset <asset-ref>

bober mission status <id>

bober services list --asset <asset-ref>
```

Exact syntax is not normative.

The architecture is.

---

# 85. First Vertical Slice — Definition of Done

The first bootstrap slice is complete only when all of the following work together:

```text
Windows:

BoberAgent Core running

Mission created

Asset stored

Workflow Goal created

Capability Registry knows node capability

Workflow starts network.service_discovery


Kali:

Execution Node receives Invocation

scope is validated

Nmap runs through Process Manager

XML is captured

Artifact is created

XML is parsed

CapabilityResult is validated


Back on Windows:

Result is ingested

Artifact is synchronized

Observation persisted

State Reducer creates Service entities

Goal is reevaluated

Workflow completes

Services can be queried after Core restart
```

---

# 86. First Vertical Slice Must Also Prove Failure Paths

The slice is NOT finished if only the happy path works.

Required tests:

```text
invalid target ref

out-of-scope target

Nmap missing

Nmap timeout

Nmap cancelled

malformed XML

Core disconnect

duplicate Invocation

duplicate Result

Artifact synchronization delayed

Execution Node restart after completed Result

Core restart before Workflow completion
```

---

# 87. What Is Deliberately Missing at First Vertical Slice

Do not block bootstrap waiting for:

```text
LLM

Semantic RAG

full Procedure library

Credentials

Secret Store production backend

Browser Sessions

Listeners

Burp

PoC execution

Privilege escalation
```

The architecture already accommodates them.

They are not required to prove the first slice.

---

# 88. Milestone 13 — First Architecture Stress Capability

After the stateless slice works, the next implementation SHOULD NOT simply add another scanner.

The next feature should stress a different architectural dimension.

Recommended:

```text
browser.interaction
```

because it tests:

```text
Resource lifetime

Session lifetime

Session drivers

exclusive leases

multiple operations against same stateful context

Resource surviving creator Run
```

---

# 89. Browser Bootstrap Sequence

Implement incrementally:

```text
Browser Resource provider

Browser Session driver

browser.interaction.create

browser.interaction.navigate

browser.interaction.screenshot

browser.interaction.close
```

Do not begin with a full autonomous web pentest.

---

# 90. Browser Acceptance

Prove:

```text
browser created by one Run

Run completes

browser remains alive

later Run navigates using SessionRef

screenshot becomes Artifact

Execution Node restart marks unrecoverable browser correctly

Core sees logical Resource/Session state
```

---

# 91. Milestone 14 — Listener and Async Session

Next architectural stress test:

```text
listener.management
```

Then:

```text
incoming reverse connection
→ Session
```

This proves that new state can originate asynchronously after the creating CapabilityRun is already complete.

---

# 92. Listener Acceptance

Prove:

```text
listener Resource survives creator Run

incoming event creates Session

Session event reaches Core

Workflow can react to newly created Session

listener can be stopped independently
```

---

# 93. Milestone 15 — Human Interaction

After durable Runs and Resources exist, implement:

```text
InteractionRequest
Checkpoint
WAITING_INPUT
InteractionResponse
resume
```

Do not begin by embedding this into a complex exploit.

Use a synthetic reference capability first.

---

# 94. Synthetic Interaction Capability

Test capability:

```text
phase 1:
ask for parameter

WAITING_INPUT

phase 2:
consume validated response

return Observation
```

Test:

```text
Core restart while waiting

Node restart while waiting

transport disconnect while waiting

response arrives later

same Run resumes
```

Only after this works should unknown-PoC human assistance depend on it.

---

# 95. Milestone 16 — Secret Store and Credential Flow

Implement before serious authentication automation.

Required:

```text
Secret storage

SecretRef

Credential entity

candidate Credential creation from Observation

credential.available Event

authorized capability secret resolution

redacted logging
```

Then implement:

```text
credential.validation
```

as the next realistic capability family.

---

# 96. Milestone 17 — Knowledge Foundation

Only after deterministic platform fundamentals are stable:

```text
Knowledge Repository

Procedure Registry

Curated Markdown loader

Knowledge IDs/versioning

Knowledge Router
```

Semantic retrieval may follow afterward.

The Procedure Registry is more important initially than vector search.

---

# 97. Milestone 18 — Semantic Retrieval

Add:

```text
Embedding Provider abstraction

Semantic Index abstraction

structural Markdown chunking

retrieval filters

retrieval regression tests
```

No GraphRAG.

No automatic Mission data ingestion into global Knowledge.

---

# 98. Milestone 19 — LLM Reasoner

Then introduce:

```text
Reasoner Provider abstraction

LM Studio provider

Context Builder

structured ActionProposal

structured InterpretationResult

validation
```

The Reasoner MUST NOT directly execute tools.

---

# 99. First LLM Use Case

Prefer a bounded task.

Example:

```text
World State contains ambiguous service/technology evidence

+
Curated Knowledge retrieved

        ↓

Reasoner proposes structured hypothesis

+
next applicable Capability
```

Do NOT make the first LLM integration:

```text
"perform full pentest autonomously"
```

---

# 100. Milestone 20 — Unknown PoC Pipeline

Only after:

```text
Artifacts

Workspaces

Resources

Sessions

Secrets

Policy

Interaction

Knowledge

Reasoner
```

are sufficiently real should the generic PoC pipeline be implemented.

Sequence:

```text
research
→ acquire
→ inspect
→ ExecutionPlan
→ validate
→ prepare runtime
→ execute
→ interpret
→ adapt
→ human assistance if required
```

This pipeline should be an integration test of the architecture, not the foundation on which the foundation is debugged.

---

# 101. Milestone Ordering Summary

Recommended order:

```text
M0   Repository / guardrails

M1   Contract models

M2   Core persistence + minimal State Reducer

M3   Capability SDK

M4   Execution Node foundation

M5   Transport abstraction + in-memory transport

M6   Artifact synchronization

M7   network.service_discovery

M8   Core Capability Registry / Router

M9   Result ingestion → World State

M10  real MCP transport

M11  minimal Workflow Engine

M12  thin CLI

====== FIRST REAL VERTICAL SLICE COMPLETE ======

M13  Browser Resource + Session

M14  Listener + asynchronous incoming Session

M15  Human interaction + durable resume

M16  Secret/Credential lifecycle

M17  Procedure/Knowledge foundation

M18  Semantic retrieval

M19  LLM Reasoner

M20  Generic unknown PoC pipeline
```

---

# 102. Why This Order Matters

This order deliberately validates architecture from simple to difficult.

```text
stateless
    ↓
persistent state
    ↓
distributed transport
    ↓
workflow
    ↓
stateful Resource
    ↓
async Session
    ↓
human wait/resume
    ↓
Secrets
    ↓
Knowledge
    ↓
Reasoning
    ↓
unknown arbitrary execution
```

Each stage stresses a new dimension while reusing the previous platform.

---

# 103. Codex Implementation Strategy

The entire Bootstrap Plan SHOULD NOT be given to Codex as one command saying:

> Implement all of this.

Each implementation session should contain one bounded milestone or sub-milestone.

Codex should always receive the repository containing the normative documentation.

---

# 104. Codex Session Pattern

Typical new implementation session:

```text
1. Read AGENTS.md.

2. Read docs/00_PROJECT_CONTEXT.md.

3. Read the normative documents relevant to this task.

4. Inspect the existing repository implementation and tests.

5. Implement only the requested milestone.

6. Do not introduce architecture outside the specification.

7. If the specification and implementation conflict,
   report the conflict instead of silently working around it.

8. Run the required tests.

9. Summarize:
   - files changed
   - behavior implemented
   - tests executed
   - remaining limitations
```

---

# 105. Codex Must Not Re-Design Opportunistically

Coding agents SHOULD NOT make decisions such as:

```text
"This would be easier if the capability writes SQLite directly."

"I'll just call subprocess from Core for now."

"I'll expose an execute_shell MCP tool."

"I'll store Nmap output directly as World State."

"I'll skip Artifact handling until later."
```

These shortcuts defeat the purpose of the bootstrap.

---

# 106. Architecture Conflict Procedure

If Codex discovers that a task cannot reasonably be implemented under the current specification:

```text
STOP the conflicting implementation path

identify exact specification conflict

explain why it blocks implementation

propose minimal architectural alternatives

do not silently modify the architecture
```

The architecture is then reviewed by the project owner before continuing.

---

# 107. Milestone Completion Rule

A milestone is not complete because:

```text
"the code exists"
```

It is complete only when:

```text
implementation exists

tests exist

tests pass

architecture boundaries remain intact

acceptance criteria are demonstrated

documentation is updated if required
```

---

# 108. No Premature Abstraction Rule

Codex SHOULD NOT build large generic frameworks for hypothetical future requirements.

Implement the Contract-required abstraction needed by the current milestone.

Examples:

```text
DO define ResourceManager interface before browser.

DO NOT implement ten unused Resource providers.

DO define Session model.

DO NOT implement SSH/WinRM/DB/browser simultaneously.

DO define Knowledge Router interface when Knowledge work begins.

DO NOT build GraphRAG because it may someday be useful.
```

---

# 109. No Premature Feature Rule

Avoid feature creep during bootstrap.

Example:

While implementing service discovery:

```text
DO:
parse services

DO NOT automatically add:
SMB enumeration
LDAP enumeration
HTTP crawling
CVE matching
credential spraying
```

Those become later Capabilities and Procedures.

---

# 110. Test Pyramid

Bootstrap testing SHOULD contain:

```text
many unit tests

many contract/schema tests

focused integration tests

small number of real end-to-end tests
```

Do not make every test require:

```text
Windows Core
+
Kali VM
+
real Nmap
```

Most logic should be testable independently.

---

# 111. Unit-Test Boundaries

Unit tests should cover:

```text
Contract validation

reducers

parsers

Attempt fingerprints

Goal predicates

Procedure evaluation

Capability logic with FakeExecutionContext

transport serialization
```

---

# 112. Integration Tests

Integration tests should cover boundaries such as:

```text
Core persistence

Execution Node ProcessManager

real Nmap fixture/lab

Artifact sync

in-memory Core ↔ Node transport

MCP Core ↔ Kali transport
```

---

# 113. End-to-End Tests

Initial E2E scenario:

```text
controlled target fixture

Windows Core

Kali Execution Node

service-discovery Workflow

Nmap capability

World State verification
```

The test MUST operate only against an explicitly controlled/authorized fixture.

---

# 114. Architecture Regression Tests

The project SHOULD eventually maintain tests that fail if:

```text
capabilities import Core

Core invokes Nmap directly

SDK imports Execution Node implementation

MCP types appear inside Contract models

plaintext secrets appear in standard Result serialization
```

Architecture is easier to preserve automatically than socially.

---

# 115. Logging from Day One

Structured logs SHOULD be present from the bootstrap.

At minimum:

```text
mission_ref
workflow_ref where applicable
run_id
capability_id
node_id
event type
timestamp
```

This will be essential once asynchronous behavior appears.

---

# 116. Correlation IDs

Stable domain IDs already provide most correlation.

Avoid inventing unrelated tracing IDs where:

```text
MissionRef
WorkflowRunRef
CapabilityRunRef
```

are sufficient.

A future distributed trace ID MAY be added independently.

---

# 117. Configuration

Separate configuration domains:

```text
Core configuration

Execution Node configuration

Capability implementation configuration
```

Do not create one giant implicit environment-variable namespace.

Configuration MUST be validated.

---

# 118. Development Environment

The project SHOULD support local development without requiring every external component.

Useful development modes:

```text
Core + fake Execution Node

Execution Node + fake Core

Capability + FakeExecutionContext

full Windows ↔ Kali deployment
```

This dramatically reduces debugging cost.

---

# 119. Reference Data Fixtures

Maintain test fixtures for:

```text
Nmap XML

Capability manifests

Invocations

Results

Observations

Events

World State

Workflow state
```

Serialized Contract fixtures help detect accidental breaking changes.

---

# 120. Contract Compatibility Tests

When Contract models change:

```text
old supported fixture
      ↓
deserialize
      ↓
validate expected compatibility
```

Breaking changes require explicit Contract-version handling.

---

# 121. Performance Is Secondary Initially

Bootstrap should prioritize:

```text
correctness
auditability
recoverability
extensibility
```

before:

```text
maximum throughput
micro-optimizations
large-scale concurrency
```

However obvious blocking design choices should be avoided.

---

# 122. First Release Boundary

A reasonable internal milestone after M12 is:

```text
BoberAgent Core Bootstrap 0.1
```

Capabilities:

```text
one real network discovery capability
```

Architecture:

```text
Core
Execution Node
transport
Artifacts
Observations
World State
Workflow
CLI
```

This is already a meaningful platform milestone even though feature coverage is intentionally tiny.

---

# 123. Second Release Boundary

A possible `0.2` milestone after M15:

```text
stateful browser
listener
Session lifecycle
human interaction
durable resume
```

This validates the hardest runtime abstractions before broad feature expansion.

---

# 124. Third Release Boundary

A possible `0.3` milestone after M19:

```text
Secrets/Credentials
Procedure Registry
Curated Knowledge
Semantic Retrieval
LLM Reasoner
```

At this stage BoberAgent begins behaving like the intended adaptive platform rather than only a deterministic orchestrator.

---

# 125. Bootstrap Success Criterion

The Bootstrap Plan succeeds if, after the first vertical slice, adding another stateless Capability requires approximately:

```text
manifest
schemas
implementation
adapter if required
tests
```

rather than:

```text
new Core execution pathway
new transport endpoint
new database special case
new workflow engine branch
```

---

# 126. Stronger Success Criterion

After later Resource/Session milestones, adding a radically different capability should still reuse:

```text
Capability Contract

SDK

Execution Node Runtime

Artifacts

World State

Workflow Engine

Policy

Events
```

without architectural exceptions.

That is the central proof that the design works.

---

# 127. Bootstrap Anti-Goals

Bootstrap is NOT successful if it produces:

```text
a powerful Nmap wrapper
but no reusable platform

a working autonomous demo
but hard-coded internals

many capabilities
but no stable Contract

an impressive LLM loop
but unreliable state

a large codebase
but no recoverability or tests
```

Depth of foundation is more valuable than breadth at this stage.

---

# 128. Final Bootstrap Rule

At every implementation step ask:

> Does this make the first capability work only, or does it establish a platform primitive that the next capabilities can reuse?

When both approaches are practical, choose the reusable platform primitive.

Do not generalize beyond demonstrated requirements.

Do not bypass the architecture merely to make the demo work faster.
