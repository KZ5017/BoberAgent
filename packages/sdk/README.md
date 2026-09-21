# boberagent-sdk

The infrastructure-independent programming boundary for BoberAgent capability authors. The SDK
contains typed interfaces only; production Process, Resource, Session, Artifact, Secret, and
interaction backends belong to the Execution Node or other owning platform component.

## Implementing a capability

Subclass `Capability` and implement its asynchronous multi-operation entry point:

```python
from boberagent_sdk import Capability, CapabilityResult, ExecutionContext
from pydantic import BaseModel


class ExampleCapability(Capability):
    capability_id = "example.analysis"

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult: ...
```

`ExecutionContext` is the complete supported platform bridge. It provides immutable invocation and
Mission views plus controlled scope, entity, process, workspace, Resource, Session, Artifact,
Secret, interaction, checkpoint, event, logging, cancellation, and clock services.

Capability code must not import Core or Execution Node internals, access their databases, mutate
World State/Mission/Scope, launch unmanaged processes, emit arbitrary administrative events, or
enumerate secrets. New facts leave a capability through Contract `CapabilityResult` objects.

Entity lookup returns small frozen SDK snapshots, not Core models. `AssetSnapshot` exposes the
address needed by target-facing capabilities; `EntitySnapshot.attributes` is the deliberate
extension point rather than a copy of the future World State ontology.

Resources and Sessions remain different SDK concepts. A Resource is managed runtime
infrastructure; a Session is a stateful semantic driver backed by one or more Resource refs.
`SessionService.create()` and `close()` operate on stable logical descriptors, while leases provide
exclusive or shared access without exposing provider objects. `BrowserSession` is the first
semantic driver: it supports scoped navigation and bounded HTML inspection without exposing
Playwright, arbitrary JavaScript, or a generic browser automation escape hatch.

`ByteStreamSession` is the generic incoming-stream driver. It exposes only timeout-bounded
`receive(max_bytes=...)` and `send(bytes)` operations plus EOF state. Socket objects, file
descriptors, listener tasks, framing assumptions, command interpretation, and provider-specific
handles remain outside the SDK. Capabilities that need JSON-safe results must explicitly encode
bounded bytes (the production listener capability uses canonical base64).

## Unit testing

Use the separately namespaced fake environment:

```python
from boberagent_sdk import AssetRef, AssetSnapshot, ProcessResult
from boberagent_sdk.testing import FakeExecutionContext

ctx = FakeExecutionContext()
ctx.entities.add(AssetSnapshot(ref=AssetRef("asset-test"), primary_address="192.0.2.10"))
ctx.scope.allow_asset(AssetRef("asset-test"))
ctx.processes.expect_tool(
    tool="fixture-tool",
    args=["--version"],
    result=ProcessResult(exit_code=0),
)
```

Close the fake context, or use it as an async context manager, to remove temporary workspaces.
Fake services never invoke subprocesses or production infrastructure.

Secret material should use `SensitiveValue`. Its ordinary string, formatting, and representation
are redacted; plaintext access is intentionally named `reveal_text()` / `reveal_bytes()`. Results,
events, diagnostics, and logs should carry `SecretRef` rather than plaintext.
