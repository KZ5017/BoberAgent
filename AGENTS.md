# BoberAgent — Coding Agent Instructions

## 1. Project

BoberAgent is a capability-driven autonomous/semi-autonomous penetration-testing orchestration platform for authorized security assessments, labs and CTF environments.

This repository is architecture-first.

Implementation convenience MUST NOT override the documented architecture.

Before making non-trivial changes, understand the relevant specifications.

---

# 2. Required Reading

Before implementing platform functionality, read:

1. `docs/00_PROJECT_CONTEXT.md`
2. `docs/01_SYSTEM_ARCHITECTURE.md`
3. the normative documents relevant to the current task.

Current normative design documents are:

```text
docs/02_CAPABILITY_CONTRACT.md
docs/03_CAPABILITY_SDK.md
docs/04_WORLD_STATE_MODEL.md
docs/05_WORKFLOW_AND_REASONING.md
docs/06_KNOWLEDGE_SYSTEM.md
docs/07_EXECUTION_NODE.md
```

Reference and implementation-planning documents:

```text
docs/08_REFERENCE_CAPABILITIES.md
docs/09_BOOTSTRAP_PLAN.md
```

Do not assume that reading only `README.md` is sufficient for architectural work.

---

# 3. Source of Truth

The documentation under `docs/` defines the intended architecture.

The following principles are especially important:

```text
Capability
= reusable system ability

Workflow / Procedure
= sequencing and decision logic

World State
= canonical operational state

Observation
= immutable evidence-derived fact

Execution Node
= runtime/execution infrastructure

LLM Reasoner
= replaceable reasoning component
```

The LLM is not the platform.

MCP is not the architecture.

Individual tools such as Nmap, NetExec, Playwright, Burp or Penelope are implementation details behind stable platform abstractions.

---

# 4. Specification Conflicts

If implementation appears to require violating a normative specification:

DO NOT silently work around it.

Instead:

1. stop the conflicting implementation path;
2. identify the exact document and rule involved;
3. explain why the current design blocks the requested implementation;
4. propose the smallest reasonable alternatives;
5. wait for the architecture to be reviewed before treating a deviation as canonical.

Implementation convenience is not sufficient justification for changing an architectural boundary.

---

# 5. Architecture Changes

Material architectural decisions MUST NOT be introduced silently.

If a change affects concepts such as:

```text
Capability semantics
World State ownership
Resource / Session semantics
transport boundaries
ExecutionContext
Workflow behavior
Knowledge architecture
human interaction
policy
persistence ownership
```

it requires architectural review and, where appropriate, an ADR under:

```text
docs/adr/
```

Do not create an ADR for ordinary implementation details.

---

# 6. Dependency Direction

The intended package dependency direction is:

```text
contracts
    ↑
    ├── sdk
    │    ↑
    │    └── capability implementations
    │
    ├── core
    │
    └── execution-node
         ↑
         └── sdk
```

Rules:

## `contracts`

MUST NOT import:

```text
core
execution-node
capability implementations
transport implementations
```

It should remain infrastructure-independent.

---

## `sdk`

MAY import:

```text
contracts
```

MUST NOT import:

```text
core
execution-node internals
capability implementations
```

---

## Capability implementations

MAY import:

```text
contracts where exposed through SDK
sdk
their own implementation/adapters
```

MUST NOT import:

```text
core internals
execution-node internals
Core database models
transport implementation
```

---

## `core`

MAY depend on:

```text
contracts
Core-owned infrastructure
```

It MUST NOT depend on concrete pentest-tool adapters such as:

```text
Nmap parser internals
NetExec implementation
Playwright implementation
```

---

## `execution-node`

MAY depend on:

```text
contracts
sdk
node-owned infrastructure
```

Capabilities are discovered/loaded through the defined plugin/runtime mechanism rather than being manually wired into Core.

---

# 7. Critical Ownership Rules

## World State

Capabilities MUST NOT write World State directly.

The required conceptual flow is:

```text
Capability
→ CapabilityResult
→ Observation
→ Observation Store
→ State Reducer
→ World State
```

Do not introduce:

```python
ctx.world_state.write(...)
```

or equivalent capability-facing functionality.

---

## Database

Capability implementations MUST NOT receive direct Core database access.

Database persistence belongs to the owning platform component.

---

## Secrets

Canonical sensitive material belongs to the Secret Store.

Use:

```text
secret_ref
credential_ref
```

where possible.

Do not propagate plaintext secrets through:

```text
ordinary CapabilityResult fields
Events
Diagnostics
logs
general semantic indexes
```

---

## Artifacts

Persistent evidence uses stable Artifact identities.

Filesystem paths are implementation details.

Do not use:

```text
/tmp/foo.xml
C:\something\output.txt
PID
file descriptor
```

as cross-component logical identities.

---

# 8. Capability Rules

A Capability represents one coherent system-level ability.

Prefer:

```text
network.service_discovery
credential.validation
browser.interaction
secret.hash_recovery
```

over tool-oriented identities such as:

```text
nmap.run
netexec.run
hashcat.run
```

A capability MAY internally use one or more tools.

Tool choice remains an implementation concern unless alternatives materially differ in risk, side effects or semantics.

---

# 9. Capability vs Workflow

Do not hide strategic orchestration inside Capability implementations.

Example:

```text
network.service_discovery discovers TCP/445
```

The capability MUST NOT therefore silently launch:

```text
SMB enumeration
credential testing
LDAP enumeration
```

Those transitions belong to Workflow / Procedure logic.

---

# 10. Execution Through SDK

Capability implementations interact with platform services through `ExecutionContext`.

The supported conceptual surface is:

```text
READ-ONLY CONTEXT
  invocation
  mission
  scope
  entities

EXECUTION
  processes
  workspace
  resources
  sessions

DATA
  artifacts
  secrets

CONTROL / OBSERVABILITY
  interactions
  checkpoints
  events
  logger
  cancellation
  clock
```

Do not bypass these abstractions merely because direct Python APIs are easier.

---

# 11. Process Execution

Do not make unmanaged process execution the default capability pattern.

Avoid direct capability usage of:

```python
subprocess.run(...)
subprocess.Popen(...)
os.system(...)
```

when ProcessService exists for the task.

Known tools execute through managed tool execution.

Unknown acquired code should execute through validated `ExecutionPlan` semantics.

Do not expose a generic unrestricted remote-shell API as the Execution Node architecture.

---

# 12. Resource and Session

Keep these concepts distinct.

```text
Resource
= runtime infrastructure

Session
= persistent stateful interaction context
```

Examples:

```text
Chromium process     → Resource
browser context      → Session

Penelope listener    → Resource
incoming shell       → Session

Python venv          → Resource
SSH connection       → Session
```

Resources and Sessions may outlive the CapabilityRun that created them.

Do not equate Resource lifetime with Run lifetime.

---

# 13. Human Interaction

Human assistance is a supported runtime state.

Capabilities MUST NOT implement private blocking console interaction such as:

```python
input(...)
```

for platform interaction.

Use:

```text
InteractionRequest
WAITING_INPUT
Checkpoint
InteractionResponse
resume
```

Human assistance is different from Policy Approval.

Never use human interaction as a workaround for a denied policy decision.

---

# 14. Unknown Results

Unknown is a legitimate result.

Do not fabricate success/failure just to simplify control flow.

When interpretation is incomplete:

```text
preserve raw Artifact
emit known Observations
emit Diagnostic where useful
return PARTIAL or UNKNOWN
```

---

# 15. Failure vs Negative Result

Do not confuse:

```text
Capability execution failed
```

with:

```text
Capability executed correctly and target condition was negative
```

Example:

```text
PoC executed correctly.
Target appears not vulnerable.
```

is normally:

```text
Run = COMPLETED
Outcome = NEGATIVE
```

not `FAILED`.

---

# 16. Async-First Design

The platform is asynchronous by design.

Do not assume:

```text
request
→ immediate result
→ done
```

The architecture must support:

```text
long scans
listeners
browsers
sessions
cracking
human interaction
disconnect/reconnect
```

Persist logical execution state where required.

Do not depend on one indefinitely alive Python coroutine for durable workflow or capability state.

---

# 17. Transport Independence

Transport-specific code belongs behind transport adapters.

If MCP is used:

```text
MCP types MUST NOT become domain types.
```

Do not place MCP-specific models into:

```text
contracts
CapabilityDefinition
CapabilityInvocation
CapabilityResult
World State
```

---

# 18. Core vs Execution Node

Core owns assessment meaning.

Execution Node owns execution mechanics.

Core should not know:

```text
Nmap command-line syntax
Playwright object handles
Penelope internals
local venv paths
process IDs
```

Execution Node should not become authoritative for:

```text
Mission
World State
Workflow strategy
Knowledge
global policy
```

---

# 19. Evidence First

Where practical, preserve raw evidence before normalization.

Parser failure must not destroy useful evidence.

Tool-specific adapters may interpret raw output into normalized Observations.

Adapters MUST NOT perform strategic Workflow decisions.

---

# 20. World State

World State is not a dump of all runtime information.

Only assessment-relevant normalized facts belong there.

Examples of information that normally remains Session/Resource runtime state:

```text
Playwright object references
DOM handles
socket objects
browser tab internals
process handles
```

---

# 21. Knowledge

Keep:

```text
Mission-specific World State
```

separate from:

```text
reusable technical Knowledge
```

Do not automatically ingest arbitrary Mission output into global Knowledge.

Do not embed plaintext secrets into general semantic indexes.

GraphRAG is not a required v1 dependency.

---

# 22. LLM Boundary

The Reasoner is advisory.

It MUST NOT directly:

```text
launch arbitrary shell commands
write World State
modify Mission Scope
override Policy
enumerate unrestricted secrets
```

LLM outputs intended for machine use should be structured and validated.

---

# 23. Testing

Every non-trivial implementation change should include appropriate tests.

Prefer:

```text
unit tests
contract/schema tests
focused integration tests
small end-to-end suite
```

Do not make all tests depend on the real Windows + Kali environment.

---

# 24. Architecture Tests

Maintain tests that protect important package boundaries.

Architectural regressions should fail automatically where practical.

Examples:

```text
capabilities importing Core
SDK importing Execution Node internals
Core importing concrete tool adapters
contracts importing infrastructure packages
```

---

# 25. Controlled Integration Targets

Integration and end-to-end security tests MUST use:

```text
local fixtures
test services
containers
authorized lab targets
```

Do not introduce arbitrary public internet targets into automated tests.

---

# 26. Development Quality

Current baseline:

```text
Python >= 3.12
Pydantic v2
asyncio-compatible async design
pytest
Ruff
mypy
```

Follow repository-configured versions and commands.

Do not add overlapping tools without justification.

---

# 27. Type Safety

Prefer typed domain models and interfaces.

Avoid spreading untyped dictionaries across component boundaries when a stable contract exists.

Do not replace semantic reference types with arbitrary strings solely for convenience.

---

# 28. Logging

Use structured logging.

Where applicable include:

```text
mission_ref
workflow_ref
run_id
capability_id
node_id
timestamp
```

Do not intentionally log secrets.

---

# 29. Configuration

Configuration must be explicit and validated.

Keep configuration domains separated where practical:

```text
Core
Execution Node
Capability/provider
```

Do not rely on large undocumented collections of environment variables.

---

# 30. No Premature Feature Expansion

Implement the requested milestone only.

Do not add unrelated capabilities because the supporting service exists.

Example:

While implementing network service discovery, do not opportunistically add:

```text
SMB enumeration
LDAP enumeration
CVE lookup
HTTP crawling
credential spraying
```

---

# 31. No Premature Abstraction

Build stable abstractions required by the architecture and current milestone.

Do not build broad unused frameworks for hypothetical needs.

Examples:

```text
Define ResourceManager interface before browser support.
Do not implement ten unused Resource providers.

Define Session model.
Do not implement every remote protocol immediately.
```

---

# 32. Existing Bober Tools

Existing projects such as:

```text
BoberAutoScanner
BoberExec
BoberCrawler
BoberWenum
```

may contain useful proven logic.

They are reference implementations / logic mines.

Do not embed them wholesale as monolithic BoberAgent capabilities.

Refactor useful logic behind professional Capability identities and platform contracts.

---

# 33. Change Scope

Before editing code:

1. inspect relevant existing implementation;
2. identify ownership of the behavior;
3. determine the smallest compliant change;
4. implement only that scope;
5. update tests;
6. run relevant quality checks.

Avoid broad unrelated cleanup in the same change unless required.

---

# 34. Completion Report

When finishing an implementation task, report:

```text
What was implemented

Files created/changed

Tests added/changed

Commands executed

Test/lint/typecheck results

Known limitations

Any architecture/specification question discovered
```

Do not claim a milestone is complete when its acceptance criteria have not been demonstrated.

---

# 35. Bootstrap Plan

Implementation order is defined by:

```text
docs/09_BOOTSTRAP_PLAN.md
```

Do not jump ahead unless explicitly instructed.

When asked to implement one Milestone, do not begin later Milestones merely because they appear related.

---

# 36. Final Rule

When choosing between:

```text
a shortcut that makes the current demo work
```

and:

```text
the documented platform primitive that future capabilities reuse
```

use the documented platform primitive.

At the same time, do not generalize beyond demonstrated requirements.

BoberAgent is intended to become powerful by accumulating reusable capabilities, procedures, knowledge and reasoning on top of a stable foundation.

Protect that foundation.
