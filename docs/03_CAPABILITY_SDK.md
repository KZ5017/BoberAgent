# BoberAgent Core — Capability SDK v1

**Status:** Initial normative SDK specification
**Document:** `docs/03_CAPABILITY_SDK.md`
**Related:** `01_SYSTEM_ARCHITECTURE.md`, `02_CAPABILITY_CONTRACT.md`

---

# 1. Purpose

The BoberAgent Capability SDK defines the supported programming interface between capability implementations and the BoberAgent platform.

The SDK exists so that capability authors can implement new system abilities without depending on BoberAgent Core internals.

A capability author should primarily need:

```text
Capability Contract
Capability SDK
operation schemas
reference implementations
contract/compliance tests
```

Knowledge of Core database structure, event-bus implementation, transport implementation or internal service layout must not be required.

---

# 2. Initial Implementation Technology

Capability SDK v1 targets:

```text
Python >= 3.12
Pydantic >= 2.x
asyncio-compatible asynchronous execution
```

Public SDK models SHOULD use Pydantic models where structured validation or serialization is required.

Public SDK interfaces MUST remain logically transport-independent.

Python implementation details MUST NOT become assumptions of the Capability Contract itself.

Future non-Python SDKs may implement the same contract.

---

# 3. Package Boundary

The SDK should be published inside the monorepo as an independent Python package.

Recommended initial structure:

```text
sdk/
└── boberagent_sdk/
    ├── __init__.py
    │
    ├── capability.py
    ├── context.py
    ├── exceptions.py
    │
    ├── models/
    │   ├── definition.py
    │   ├── invocation.py
    │   ├── run.py
    │   ├── result.py
    │   ├── observation.py
    │   ├── finding.py
    │   ├── artifact.py
    │   ├── resource.py
    │   ├── session.py
    │   ├── effect.py
    │   ├── diagnostic.py
    │   ├── event.py
    │   ├── execution_plan.py
    │   └── interaction.py
    │
    ├── services/
    │   ├── artifacts.py
    │   ├── cancellation.py
    │   ├── clock.py
    │   ├── entities.py
    │   ├── events.py
    │   ├── interactions.py
    │   ├── processes.py
    │   ├── resources.py
    │   ├── secrets.py
    │   ├── sessions.py
    │   └── workspace.py
    │
    └── testing/
        ├── fake_context.py
        ├── contract.py
        └── fixtures.py
```

Capability implementations MUST import supported platform-facing APIs from the SDK package rather than importing Core or Execution Node internals.

---

# 4. Capability Entry Point

Every executable capability implementation MUST expose a standard capability object.

Conceptually:

```python
from boberagent_sdk import Capability, ExecutionContext, CapabilityResult


class NetworkServiceDiscovery(Capability):
    capability_id = "network.service_discovery"

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: object,
    ) -> CapabilityResult:
        ...
```

The exact base-class mechanics MAY evolve, but the logical interface MUST remain equivalent to:

```text
operation
+
ExecutionContext
+
validated operation input
        ↓
Capability implementation
        ↓
CapabilityResult
```

A capability MUST NOT require BoberAgent Core objects outside this interface.

---

# 5. Manifest and Implementation Separation

The static CapabilityDefinition belongs to the capability manifest.

Example:

```text
capability.yaml
```

Implementation code MUST NOT be executed merely to discover basic capability metadata.

The runtime:

1. loads and validates the manifest;
2. validates contract compatibility;
3. locates the declared implementation entry point;
4. only then imports or executes implementation code.

This enables safe discovery and inspection without arbitrary plugin execution.

---

# 6. ExecutionContext

Every invocation receives an `ExecutionContext`.

`ExecutionContext` is the complete supported bridge from capability implementation code into BoberAgent platform services.

Conceptually:

```python
class ExecutionContext:
    invocation: InvocationContext
    mission: MissionContext
    scope: ScopeService
    entities: EntityReader

    processes: ProcessService
    workspace: WorkspaceService
    resources: ResourceService
    sessions: SessionService

    artifacts: ArtifactService
    secrets: SecretService

    interactions: InteractionService
    events: EventService
    logger: CapabilityLogger
    cancellation: CancellationService
    clock: ClockService
```

The context MUST NOT expose:

```text
database connection
World State writer
Mission writer
Scope writer
Policy override
Capability Registry writer
unrestricted Event Bus
unrestricted Secret Store
```

---

# 7. ExecutionContext Lifetime

One logical ExecutionContext belongs to one CapabilityRun.

A capability MUST NOT persist the ExecutionContext object itself as durable state.

Durable references such as:

```text
artifact_ref
resource_ref
session_ref
secret_ref
```

MAY be persisted through Checkpoints.

The runtime MAY reconstruct a new ExecutionContext when a Run resumes.

Capability code MUST therefore not rely on process-local object identity surviving pause, restart or recovery.

---

# 8. Invocation Context

`ctx.invocation` is read-only.

It SHOULD expose:

```python
ctx.invocation.run_id
ctx.invocation.capability_id
ctx.invocation.operation
ctx.invocation.mission_ref
ctx.invocation.parent_run_ref
ctx.invocation.workflow_run_ref
```

The implementation MUST NOT mutate invocation metadata.

---

# 9. Mission Context

`ctx.mission` provides the minimal read-only Mission information required for execution.

It MAY expose:

```text
mission_id
mission profile
objectives
policy profile reference
timestamps
```

A capability MUST NOT modify Mission configuration.

A capability MUST NOT use Mission Context as an unrestricted gateway to unrelated World State.

---

# 10. Scope Service

`ctx.scope` provides scope-validation functionality.

Example conceptual API:

```python
await ctx.scope.assert_asset_allowed(asset_ref)
await ctx.scope.assert_address_allowed(address)
allowed = await ctx.scope.contains(asset_ref)
```

Target-facing activity MUST pass scope validation before execution.

The runtime SHOULD validate target scope before the implementation begins.

The capability MAY request additional validation when dynamically resolved targets appear during execution.

A capability MUST NOT expand or modify scope.

---

# 11. Entity Reader

`ctx.entities` provides controlled read access to Core-domain objects needed by the invocation.

Conceptual API:

```python
host = await ctx.entities.get(asset_ref)
service = await ctx.entities.get(service_ref)
credential = await ctx.entities.get(credential_ref)
```

Typed helpers MAY exist:

```python
host = await ctx.entities.asset(asset_ref)
service = await ctx.entities.service(service_ref)
```

The Entity Reader MUST be read-only.

No supported SDK API equivalent to the following may exist:

```python
ctx.entities.update(...)
ctx.entities.delete(...)
ctx.world_state.write(...)
```

If an implementation needs to communicate new information, it MUST return it through CapabilityResult or controlled platform services.

---

# 12. Artifact Service

All durable raw evidence and generated non-secret data SHOULD be stored through `ctx.artifacts`.

Conceptual operations:

```python
artifact = await ctx.artifacts.create_from_bytes(...)
artifact = await ctx.artifacts.create_from_file(...)
artifact = await ctx.artifacts.create_text(...)
artifact = await ctx.artifacts.get(artifact_ref)
```

The Artifact Service owns:

```text
logical identity
storage
hashing
metadata
provenance
ownership
```

Capability code MAY use temporary local paths internally while actively processing data.

It MUST NOT expose those physical paths as durable platform identities.

---

# 13. Artifact Creation

Example:

```python
artifact = await ctx.artifacts.create_from_file(
    artifact_type="network_scan.nmap_xml",
    path=xml_file,
    metadata={
        "tool": "nmap",
    },
)
```

The returned object SHOULD contain a stable:

```text
artifact_ref
```

The implementation then references the artifact rather than the source path.

---

# 14. Workspace Service

`ctx.workspace` provides managed temporary or persistent execution workspaces.

Conceptual API:

```python
workspace = await ctx.workspace.create(
    purpose="poc_execution",
    isolation="run",
)
```

A Workspace handle MAY expose a runtime-local path to the implementation.

That path is valid only as an implementation detail.

Examples of Workspace use:

```text
Git repository checkout
PoC modification
compilation
temporary output
virtual environment preparation
generated files
```

Workspaces MUST have ownership and cleanup semantics.

---

# 15. Process Service

Capability implementations SHOULD NOT use:

```python
subprocess.run(...)
subprocess.Popen(...)
os.system(...)
```

for platform-managed execution.

They SHOULD use:

```text
ctx.processes
```

instead.

This enables:

```text
audit
timeout
cancellation
stdout/stderr capture
Artifact generation
tool identity
process ownership
policy enforcement
```

---

# 16. Known Tool Execution

Known tools use managed tool execution.

Conceptual API:

```python
process_result = await ctx.processes.run_tool(
    tool="nmap",
    args=[
        "-sV",
        "-oX",
        output_file,
        address,
    ],
    timeout=600,
)
```

The Process Service SHOULD resolve the executable from the registered Execution Node environment.

Capabilities SHOULD NOT hard-code absolute tool paths unless the implementation explicitly requires them.

---

# 17. Process Arguments and Secrets

Secrets MUST NOT be unnecessarily embedded into process arguments.

Where supported, sensitive input SHOULD use:

```text
environment injection
stdin
temporary protected files
tool-specific secure mechanisms
```

rather than command-line arguments visible in logs or process listings.

The Process Manager MUST support secret-aware redaction.

---

# 18. Arbitrary or Unknown Code Execution

Unknown acquired code, especially PoCs, MUST NOT use the ordinary known-tool path as an unrestricted shell escape.

It SHOULD be executed through:

```python
await ctx.processes.execute_plan(
    execution_plan_ref=plan_ref,
    runtime_ref=runtime_ref,
)
```

The runtime MUST validate the ExecutionPlan before execution.

Validation may include:

```text
policy
scope
runtime availability
dependencies
bindings
expected effects
isolation requirements
```

An ExecutionPlan is structured intent, not an opaque shell command.

---

# 19. Shell Execution

The SDK SHOULD NOT expose a general-purpose convenience API equivalent to:

```python
ctx.shell("arbitrary command")
```

as the default mechanism.

Where shell execution is genuinely required by a trusted implementation, it MUST be explicitly represented as managed execution and remain subject to audit and policy.

The existence of a shell-based tool MUST NOT become a bypass around Process Manager controls.

---

# 20. Resource Service

`ctx.resources` manages runtime infrastructure.

Conceptual API:

```python
resource = await ctx.resources.create(
    resource_type="python_environment",
    configuration={...},
)

resource = await ctx.resources.get(resource_ref)

lease = await ctx.resources.acquire(
    resource_ref,
    mode="exclusive",
)

await ctx.resources.release(lease)
await ctx.resources.close(resource_ref)
```

Only registered Resource types MAY be created.

Capability code MUST NOT directly modify Resource Registry state.

---

# 21. Resource Providers

A Resource type MAY be backed by a registered provider.

Examples:

```text
python_environment → PythonEnvironmentProvider
listener           → PenelopeListenerProvider
browser_process    → PlaywrightBrowserProvider
burp_project       → BurpProvider
```

The provider implementation belongs to Execution Node runtime infrastructure or a dedicated capability/runtime extension.

Capability authors SHOULD operate through ResourceService rather than depend on provider internals.

---

# 22. Session Service

`ctx.sessions` manages persistent interaction contexts.

Conceptual API:

```python
session = await ctx.sessions.get(session_ref)

async with ctx.sessions.acquire(
    session_ref,
    mode="exclusive",
) as session:
    ...
```

Session operations SHOULD be exposed through capability-oriented driver interfaces.

Examples:

```text
command execution
file upload
file download
browser navigation
database query
HTTP-session interaction
```

The generic Session object MUST NOT expose transport-specific internals as its public platform identity.

---

# 23. Session Drivers

The runtime resolves a Session to a SessionDriver.

Examples:

```text
RemoteShellSessionDriver
SSHSessionDriver
WinRMSessionDriver
BrowserSessionDriver
DatabaseSessionDriver
WebSessionDriver
```

A SessionDriver may expose type-specific operation protocols.

For example:

```python
class CommandSession(Protocol):
    async def execute(self, command: str) -> CommandResult:
        ...
```

or:

```python
class BrowserSession(Protocol):
    async def navigate(self, url: str) -> NavigationResult:
        ...
```

Capabilities SHOULD request the capability of a Session rather than its underlying product or transport.

---

# 24. Session Acquisition and Locking

Operations that mutate stateful Session context SHOULD acquire an exclusive lease.

Example:

```python
async with ctx.sessions.acquire(
    session_ref,
    mode="exclusive",
) as browser:
    await browser.navigate(url)
```

Read-only Session operations MAY use shared access where the Session type safely supports it.

A capability MUST NOT bypass Session locking.

---

# 25. Secret Service

`ctx.secrets` is the only supported capability-facing API for canonical secret material.

It supports two primary directions:

```text
resolve existing secret
store newly discovered/generated secret
```

---

# 26. Resolving Secrets

Example:

```python
secret = await ctx.secrets.resolve(
    secret_ref,
    purpose="authentication",
)
```

Secret resolution MUST be:

```text
purpose-aware
run-associated
auditable
policy-controlled
```

The Secret Service MAY return a short-lived sensitive wrapper instead of an ordinary Python string.

Sensitive wrappers SHOULD reduce accidental logging or serialization.

---

# 27. Creating Secrets

A capability that recovers or creates sensitive material MAY call:

```python
secret_ref = await ctx.secrets.store(
    value=recovered_value,
    secret_type="password",
    metadata={...},
)
```

The returned reference MAY then appear in Observations or structured results.

Plain secret values MUST NOT be placed into:

```text
ordinary CapabilityResult fields
Events
Diagnostics
logs
```

---

# 28. Logging

`ctx.logger` provides structured logging.

Example:

```python
ctx.logger.info(
    "Starting service discovery",
    target_ref=target_ref,
)
```

The runtime SHOULD automatically attach:

```text
run_id
mission_id
capability_id
operation
execution_node
timestamp
```

The logger MUST apply registered sensitive-value redaction.

Capability authors MUST NOT intentionally log plaintext secrets.

---

# 29. Event Service

`ctx.events` allows capability implementations to publish allowed runtime events.

Common convenience operations MAY include:

```python
await ctx.events.progress(
    message="Scanning selected ports",
    current=20,
    total=100,
)
```

and controlled structured events.

A capability MUST NOT gain unrestricted authority to emit Core-owned administrative events.

The Event Service SHOULD validate event type ownership.

---

# 30. Cancellation Service

`ctx.cancellation` provides cooperative cancellation.

Conceptual API:

```python
if ctx.cancellation.requested:
    ...

await ctx.cancellation.checkpoint()
```

Managed Process, Resource and Session services SHOULD automatically cooperate with cancellation where practical.

A long-running pure-Python implementation MUST periodically observe cancellation state.

---

# 31. Clock Service

`ctx.clock` provides platform-consistent time.

Conceptual API:

```python
now = ctx.clock.now()
```

Capability logic that affects persisted lifecycle timestamps SHOULD prefer the SDK clock over direct system-clock access.

This improves deterministic testing and future replay/simulation support.

---

# 32. Interaction Service

Human or external assistance is requested through:

```text
ctx.interactions
```

A capability MUST NOT use private blocking console input.

Example:

```python
response = await ctx.interactions.request(
    interaction_type="choice",
    title="Select alternative payload family",
    message="Known variants did not establish a session.",
    schema={
        "type": "string",
        "enum": [
            "bash",
            "sh",
            "python",
            "php",
            "custom",
        ],
    },
)
```

The runtime handles:

```text
InteractionRequest creation
checkpointing
WAITING_INPUT transition
routing
response validation
resume
audit
```

---

# 33. Durable Human Interaction

The SDK MUST NOT require the Python coroutine stack to remain alive while waiting indefinitely for human input.

The developer-facing `await ctx.interactions.request(...)` MAY appear synchronous from capability code, but the runtime implementation MUST support durable suspension and reconstruction.

This MAY be implemented internally through:

```text
explicit state machine
checkpoint + resume token
runtime continuation abstraction
```

but MUST NOT rely solely on one in-memory coroutine surviving indefinitely.

---

# 34. Checkpoint API

Capabilities that contain resumable multi-phase logic MAY explicitly create checkpoints.

Conceptual API:

```python
await ctx.checkpoint.save(
    phase="payload_selection",
    state={
        "attempted_variants": ["bash", "python"],
        "listener_ref": listener_ref,
        "artifact_ref": poc_ref,
    },
)
```

If exposed directly, Checkpoint Service becomes part of ExecutionContext.

Alternatively, InteractionService and Runtime MAY manage common checkpoints automatically.

SDK v1 SHOULD expose an explicit checkpoint facility for advanced capabilities.

Recommended ExecutionContext extension:

```text
ctx.checkpoints
```

---

# 35. Checkpoint Constraints

Checkpoint data MUST:

* be serializable;
* use stable references rather than live runtime objects;
* avoid unnecessary secret material;
* contain enough state to continue logically.

Checkpoint data MUST NOT contain:

```text
open socket object
Python coroutine
file descriptor
Playwright object instance
database connection object
```

Such live objects are represented by Resource or Session handles.

---

# 36. Capability Result Construction

The SDK SHOULD provide typed helpers for building CapabilityResult.

Example:

```python
return CapabilityResult(
    execution_status="COMPLETED",
    outcome=CapabilityOutcome(
        category="SUCCESS",
    ),
    observations=observations,
    artifacts=[raw_xml],
)
```

CapabilityResult validation MUST occur before leaving the Execution Node.

Malformed result objects MUST NOT be accepted into Core state processing.

---

# 37. Observation Construction

SDK helpers SHOULD ensure provenance is automatically attached.

Instead of requiring every implementation to repeat:

```text
run_ref
timestamp
mission_ref
```

the SDK MAY provide:

```python
observation = ctx.observations.create(
    observation_type="network.service",
    subject_ref=asset_ref,
    value={...},
    evidence_refs=[artifact_ref],
    confidence=1.0,
)
```

If such a helper is provided, it creates an in-memory/return object only.

It MUST NOT write canonical World State.

---

# 38. Finding Construction

A similar helper MAY exist:

```python
finding = ctx.findings.create(...)
```

Finding creation does not imply final truth.

The Core remains responsible for persistence, deduplication and state interpretation.

---

# 39. Effect Construction

Capability implementations that verify a target-side modification SHOULD return a typed Effect.

Example:

```python
effect = Effect(
    type="target.service_configuration_change",
    subject_ref=service_ref,
    action="modify",
    intentional=True,
    confirmed=True,
    evidence_refs=[artifact_ref],
)
```

The SDK SHOULD support cleanup metadata.

Example:

```text
reversible
cleanup capability
cleanup input references
```

The capability MUST NOT directly update AccessContext or other canonical state merely because it emitted an Effect.

---

# 40. Capability-Owned Internal Logic

Capability implementation MAY freely organize internal code such as:

```text
executors
normalizers
tool adapters
parsers
validators
domain-specific helpers
```

provided that external platform communication occurs through the SDK.

Recommended package:

```text
capabilities/
└── network_service_discovery/
    ├── capability.yaml
    ├── schemas/
    ├── implementation/
    │   ├── capability.py
    │   └── executor.py
    ├── adapters/
    │   └── nmap_xml.py
    ├── tests/
    └── README.md
```

---

# 41. Tool Adapter Responsibility

A tool adapter handles tool-specific details.

Examples:

```text
CLI syntax
version-specific output
XML/JSON parsing
exit-code interpretation
tool quirks
```

An adapter MUST NOT own workflow decisions.

Example:

```text
Nmap adapter:
"TCP/445 is open."

NOT:

"Therefore automatically run SMB enumeration."
```

The latter belongs to Workflow/Procedure logic.

---

# 42. Normalization

When deterministic machine-readable output exists, deterministic parsing SHOULD be preferred.

Examples:

```text
XML
JSON
structured API response
```

If deterministic interpretation is not possible, an implementation MAY request an LLM-backed interpreter through a platform service once such a service is formally exposed.

Direct ad-hoc model access from capability code SHOULD NOT become the default pattern.

LLM usage SHOULD remain auditable and replaceable.

---

# 43. Capability Internal State

Short-lived operation-local state MAY remain ordinary local variables.

State that must survive:

```text
pause
WAITING_INPUT
runtime restart
Execution Node restart
```

MUST be represented using:

```text
Artifact
Resource
Session
Secret
Checkpoint
```

or another approved persistent platform primitive.

---

# 44. Capability Dependencies

The SDK runtime MUST provide dependency resolution results before invoking the implementation.

Capability authors SHOULD NOT independently discover platform-level dependency state through arbitrary shell commands when a registered dependency system exists.

Example:

```text
tool: nmap
minimum version: 7.90
```

The implementation may receive a resolved Tool handle or trust runtime validation.

---

# 45. Errors and Exceptions

The SDK MUST define a controlled exception hierarchy.

Initial classes SHOULD include equivalents of:

```text
CapabilityError
InputError
DependencyError
ScopeViolation
PolicyDenied
ResourceUnavailable
SessionUnavailable
ExecutionTimeout
ExecutionCancelled
ToolExecutionError
ResultValidationError
```

Capability implementations MAY raise controlled SDK exceptions.

The Runtime converts these into:

```text
CapabilityRun terminal state
Diagnostic records
Events
```

Unhandled exceptions are treated as implementation/runtime failures.

They MUST NOT be silently converted into negative pentest results.

---

# 46. Negative Assessment Outcomes

Expected negative security results SHOULD be returned normally.

Example:

```python
return CapabilityResult(
    execution_status="COMPLETED",
    outcome=CapabilityOutcome(
        category="NEGATIVE",
        code="TARGET_NOT_VULNERABLE",
    ),
)
```

The following SHOULD NOT be used:

```python
raise ToolExecutionError("Target not vulnerable")
```

unless the requested test itself genuinely failed.

---

# 47. Unknown Outcomes

A capability MAY return:

```python
CapabilityOutcome(
    category="UNKNOWN",
    code="UNCLASSIFIED_TOOL_RESULT",
)
```

while preserving:

```text
Artifact refs
Diagnostics
Observations
```

This is preferable to inventing certainty.

---

# 48. Policy Boundary

Capability code MAY declare behavior through its manifest and request platform operations through SDK services.

Capability code MUST NOT determine that an otherwise denied operation is safe to bypass.

Policy remains externally owned.

If policy denies an SDK operation, the capability MUST accept that result.

---

# 49. Capability Isolation

SDK v1 MUST avoid requiring same-process global state.

Capability code SHOULD be compatible with future execution in:

```text
dedicated subprocess
isolated worker
container
remote worker
```

Therefore capability code MUST NOT rely on:

```text
shared mutable global Core objects
direct Core database handles
process-global session registries
unmanaged live references from previous invocations
```

---

# 50. Local vs Remote Execution

The same logical SDK SHOULD work whether the capability provider is:

```text
local to BoberAgent Core
Kali Execution Node
future remote Execution Node
```

Transport details MUST remain hidden from the capability implementation.

---

# 51. Reference Implementation — Network Service Discovery

Conceptually:

```python
class NetworkServiceDiscovery(Capability):

    capability_id = "network.service_discovery"

    async def execute(
        self,
        operation,
        ctx,
        inputs,
    ):
        target = await ctx.entities.get(inputs.target_ref)

        await ctx.scope.assert_asset_allowed(inputs.target_ref)

        workspace = await ctx.workspace.create(
            purpose="network-service-discovery",
            isolation="run",
        )

        xml_path = workspace.path / "scan.xml"

        process = await ctx.processes.run_tool(
            tool="nmap",
            args=[
                "-sV",
                "-oX",
                str(xml_path),
                target.primary_address,
            ],
            timeout=inputs.timeout,
        )

        raw_xml = await ctx.artifacts.create_from_file(
            artifact_type="network_scan.nmap_xml",
            path=xml_path,
        )

        observations = parse_nmap_xml(
            raw_xml,
            target_ref=inputs.target_ref,
        )

        return CapabilityResult(
            execution_status="COMPLETED",
            outcome=CapabilityOutcome(
                category="SUCCESS",
            ),
            artifacts=[raw_xml],
            observations=observations,
        )
```

This example is illustrative.

Exact command arguments belong to implementation policy, not this SDK specification.

---

# 52. Reference Implementation — Browser Interaction

Creation:

```python
browser_resource = await ctx.resources.create(
    resource_type="browser_process",
    configuration={
        "engine": "chromium",
    },
)

browser_session = await ctx.sessions.create(
    session_type="browser",
    resource_refs=[browser_resource.ref],
)
```

Interaction:

```python
async with ctx.sessions.acquire(
    inputs.session_ref,
    mode="exclusive",
) as browser:

    navigation = await browser.navigate(inputs.url)

    screenshot = await ctx.artifacts.create_from_bytes(
        artifact_type="browser.screenshot",
        data=await browser.screenshot(),
    )
```

The capability does not access Playwright objects outside the Session driver boundary.

---

# 53. Reference Implementation — Hash Recovery

A local-compute capability may have no target.

Conceptually:

```python
hash_artifact = await ctx.artifacts.get(inputs.hash_artifact_ref)

result = await ctx.processes.run_tool(
    tool="hashcat",
    args=[...],
    timeout=inputs.timeout,
)

if result.recovered_secret:
    secret_ref = await ctx.secrets.store(
        value=result.recovered_secret,
        secret_type="password",
    )
```

The returned Observation references `secret_ref`.

The plaintext recovered secret is not returned in ordinary CapabilityResult serialization.

---

# 54. Reference Implementation — Human-Assisted PoC

Conceptually:

```python
for variant in known_variants:
    result = await attempt_variant(variant)

    if result.session_created:
        return success(result)

response = await ctx.interactions.request(
    interaction_type="structured_form",
    title="PoC requires assistance",
    message="Known payload variants failed.",
    schema={
        "type": "object",
        "properties": {
            "action": {
                "enum": [
                    "retry_variant",
                    "provide_custom_value",
                    "stop",
                ]
            },
            "value": {
                "type": ["string", "null"]
            },
        },
        "required": ["action"],
    },
)
```

The Runtime may suspend and later reconstruct the Run while waiting.

The capability implementation MUST NOT assume the original Python stack remains continuously resident.

---

# 55. SDK Testing Utilities

The SDK SHOULD provide a fake/in-memory ExecutionContext for unit tests.

Example:

```python
ctx = FakeExecutionContext()

ctx.entities.add(...)
ctx.scope.allow(...)
ctx.processes.expect_tool(...)
```

This allows capability tests without launching the entire BoberAgent Core.

Testing helpers SHOULD support:

```text
fake artifacts
fake sessions
fake resources
fake secrets
fake clock
cancellation
interaction responses
```

---

# 56. Contract Compliance Tests

Every capability package SHOULD be testable with a standard compliance runner.

Conceptually:

```text
bober-agent capability validate ./capabilities/foo
```

Validation SHOULD check:

```text
manifest/schema validity
SDK compatibility
operation exposure
dependency declarations
input validation
result validation
scope behavior
side-effect declaration
retry semantics
secret handling
Artifact provenance
Resource/Session behavior
cancellation
human interaction semantics
```

Capability-specific functional tests are additional.

---

# 57. Capability Author Experience

A compliant capability author should normally implement only:

```text
capability manifest
operation schemas
domain logic
tool/runtime adapter
normalization
tests
```

The author should not implement:

```text
Mission storage
World State mutation
generic persistence
Event Bus
Secret database
Resource Registry
Session Registry
policy engine
MCP protocol handling
general run lifecycle
```

These are platform responsibilities.

---

# 58. SDK Stability Rule

Once Capability SDK v1 is used by multiple capabilities, changes to its public interface MUST be treated as platform API changes.

Internal implementation details MAY evolve freely.

Public behavior or signature changes SHOULD:

1. preserve compatibility where practical;
2. be versioned when breaking;
3. update reference capabilities;
4. update contract tests;
5. be documented through an ADR when architectural semantics change.

---

# 59. Implementation Rule for Coding Agents

A coding agent implementing capability functionality MUST treat this document and `02_CAPABILITY_CONTRACT.md` as authoritative.

If implementing a requested capability appears to require:

```text
direct World State mutation
direct database access
unmanaged canonical Resources
plaintext secret propagation
private blocking human input
unmanaged arbitrary process execution
```

the agent MUST NOT silently introduce the shortcut.

It must identify the conflict with the SDK/Contract boundary so the architecture can be reviewed.

---

# 60. Capability SDK v1 Acceptance Goal

The SDK boundary is considered successful when the following can all be implemented without importing BoberAgent Core internals:

```text
network.service_discovery

stateful browser interaction

listener management

remote-session interaction

local JWT/hash analysis

unknown PoC execution

privilege/access transition capability

human-assisted capability
```

If these require repeated SDK bypasses, the SDK design must be reconsidered before capability coverage expands.
