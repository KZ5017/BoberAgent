"""High-quality in-memory SDK services for capability unit tests only."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import TracebackType

from boberagent_contracts import (
    AccessMode,
    ArtifactDescriptor,
    ArtifactRef,
    AssetRef,
    CapabilityRunRef,
    Checkpoint,
    CheckpointRef,
    DomainRef,
    Event,
    EventRef,
    ExecutionPlan,
    ExecutionPlanRef,
    InteractionRequest,
    InteractionResponse,
    JsonObject,
    JsonValue,
    MissionRef,
    ResourceDescriptor,
    ResourceRef,
    SecretRef,
    SessionDescriptor,
    SessionRef,
    StorageRef,
    validate_interaction_response,
)
from pydantic import BaseModel, ConfigDict, Field

from boberagent_sdk.exceptions import (
    DependencyError,
    ExecutionCancelled,
    InputError,
    InteractionUnavailable,
    ResourceUnavailable,
    ScopeViolation,
    SessionUnavailable,
    ToolExecutionError,
)
from boberagent_sdk.services.entities import AssetSnapshot, EntitySnapshot
from boberagent_sdk.services.processes import ProcessResult
from boberagent_sdk.services.resources import ResourceLease
from boberagent_sdk.services.secrets import SensitiveValue
from boberagent_sdk.services.sessions import SessionDriver, SessionHandle, SessionLease
from boberagent_sdk.services.workspace import (
    Workspace,
    WorkspaceIsolation,
    WorkspaceRef,
)


class FakeClock:
    """Deterministic, explicitly advanced test clock."""

    def __init__(self, now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("FakeClock requires a timezone-aware timestamp")
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("FakeClock requires a timezone-aware timestamp")
        self._now = value


class FakeScopeService:
    def __init__(
        self,
        *,
        allowed_assets: set[AssetRef] | None = None,
        allowed_addresses: set[str] | None = None,
    ) -> None:
        self._assets = set(allowed_assets or ())
        self._addresses = set(allowed_addresses or ())

    def allow_asset(self, asset_ref: AssetRef) -> None:
        self._assets.add(asset_ref)

    def allow_address(self, address: str) -> None:
        self._addresses.add(address)

    async def contains_asset(self, asset_ref: AssetRef) -> bool:
        return asset_ref in self._assets

    async def assert_asset_allowed(self, asset_ref: AssetRef) -> None:
        if not await self.contains_asset(asset_ref):
            raise ScopeViolation(f"Asset is outside test scope: {asset_ref}")

    async def contains_address(self, address: str) -> bool:
        return address in self._addresses

    async def assert_address_allowed(self, address: str) -> None:
        if not await self.contains_address(address):
            raise ScopeViolation(f"Address is outside test scope: {address}")


class FakeEntityReader:
    def __init__(self) -> None:
        self._entities: dict[str, EntitySnapshot | AssetSnapshot] = {}

    def add(self, snapshot: EntitySnapshot | AssetSnapshot) -> None:
        self._entities[str(snapshot.ref)] = snapshot.model_copy(deep=True)

    async def get(self, ref: DomainRef) -> EntitySnapshot | AssetSnapshot:
        try:
            return self._entities[str(ref)].model_copy(deep=True)
        except KeyError as error:
            raise DependencyError(f"Unknown entity reference: {ref}") from error

    async def asset(self, asset_ref: AssetRef) -> AssetSnapshot:
        snapshot = await self.get(asset_ref)
        if not isinstance(snapshot, AssetSnapshot):
            raise DependencyError(f"Entity is not an Asset snapshot: {asset_ref}")
        return snapshot


class FakeArtifactService:
    def __init__(self, run_ref: CapabilityRunRef, clock: FakeClock) -> None:
        self._run_ref = run_ref
        self._clock = clock
        self._counter = 0
        self._descriptors: dict[str, ArtifactDescriptor] = {}
        self._content: dict[str, bytes] = {}

    async def create_from_bytes(
        self,
        *,
        artifact_type: str,
        data: bytes,
        media_type: str | None = None,
        metadata: JsonObject | None = None,
    ) -> ArtifactDescriptor:
        self._counter += 1
        artifact_ref = ArtifactRef(f"artifact-{self._counter:04d}")
        descriptor = ArtifactDescriptor(
            artifact_id=artifact_ref,
            artifact_type=artifact_type,
            storage_ref=StorageRef(f"fake-storage:{artifact_ref}"),
            created_by_run=self._run_ref,
            created_at=self._clock.now(),
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            media_type=media_type,
            metadata={} if metadata is None else metadata,
        )
        self._descriptors[str(artifact_ref)] = descriptor.model_copy(deep=True)
        self._content[str(artifact_ref)] = bytes(data)
        return descriptor

    async def create_from_file(
        self,
        *,
        artifact_type: str,
        path: Path,
        media_type: str | None = None,
        metadata: JsonObject | None = None,
    ) -> ArtifactDescriptor:
        return await self.create_from_bytes(
            artifact_type=artifact_type,
            data=path.read_bytes(),
            media_type=media_type,
            metadata=metadata,
        )

    async def create_text(
        self,
        *,
        artifact_type: str,
        text: str,
        media_type: str = "text/plain",
        metadata: JsonObject | None = None,
    ) -> ArtifactDescriptor:
        return await self.create_from_bytes(
            artifact_type=artifact_type,
            data=text.encode(),
            media_type=media_type,
            metadata=metadata,
        )

    async def get(self, artifact_ref: ArtifactRef) -> ArtifactDescriptor:
        try:
            return self._descriptors[str(artifact_ref)].model_copy(deep=True)
        except KeyError as error:
            raise DependencyError(f"Unknown Artifact: {artifact_ref}") from error

    async def read_bytes(self, artifact_ref: ArtifactRef) -> bytes:
        try:
            return bytes(self._content[str(artifact_ref)])
        except KeyError as error:
            raise DependencyError(f"Unknown Artifact: {artifact_ref}") from error


class FakeWorkspaceService:
    def __init__(self, run_ref: CapabilityRunRef) -> None:
        self._run_ref = run_ref
        self._root = tempfile.TemporaryDirectory(prefix="boberagent-sdk-")
        self._counter = 0
        self._workspaces: dict[str, Workspace] = {}
        self._closed = False

    async def create(
        self,
        *,
        purpose: str,
        isolation: WorkspaceIsolation = WorkspaceIsolation.RUN,
        owner_ref: DomainRef | None = None,
    ) -> Workspace:
        if self._closed:
            raise RuntimeError("fake workspace service is closed")
        if not purpose:
            raise InputError("workspace purpose must not be empty")
        self._counter += 1
        workspace_ref = WorkspaceRef(f"workspace-{self._counter:04d}")
        path = Path(self._root.name) / str(workspace_ref)
        path.mkdir()
        workspace = Workspace(
            workspace_ref=workspace_ref,
            purpose=purpose,
            isolation=isolation,
            owner_ref=owner_ref or self._run_ref,
            path=path,
        )
        self._workspaces[str(workspace_ref)] = workspace
        return workspace

    @property
    def root_path(self) -> Path:
        """Expose the temporary managed root so tests can predict tool output paths."""

        return Path(self._root.name)

    async def cleanup(self, workspace_ref: WorkspaceRef) -> None:
        try:
            workspace = self._workspaces.pop(str(workspace_ref))
        except KeyError as error:
            raise DependencyError(f"Unknown Workspace: {workspace_ref}") from error
        shutil.rmtree(workspace.path)

    def close(self) -> None:
        if not self._closed:
            self._root.cleanup()
            self._workspaces.clear()
            self._closed = True


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    tool: str
    args: tuple[str, ...]
    timeout: float | None


@dataclass(frozen=True, slots=True)
class _ToolExpectation:
    invocation: ToolInvocation
    result: ProcessResult
    file_outputs: tuple[tuple[Path, bytes], ...] = ()


class FakeProcessService:
    def __init__(self) -> None:
        self._expectations: list[_ToolExpectation] = []
        self._plan_results: dict[str, ProcessResult] = {}
        self.invocations: list[ToolInvocation] = []

    def expect_tool(
        self,
        *,
        tool: str,
        args: list[str] | tuple[str, ...],
        result: ProcessResult,
        timeout: float | None = None,
        file_outputs: Mapping[Path, bytes] | None = None,
    ) -> None:
        invocation = ToolInvocation(tool=tool, args=tuple(args), timeout=timeout)
        outputs = () if file_outputs is None else tuple(file_outputs.items())
        self._expectations.append(
            _ToolExpectation(invocation=invocation, result=result, file_outputs=outputs)
        )

    def expect_plan(self, plan_ref: ExecutionPlanRef, *, result: ProcessResult) -> None:
        self._plan_results[str(plan_ref)] = result

    async def run_tool(
        self,
        *,
        tool: str,
        args: list[str] | tuple[str, ...],
        timeout: float | None = None,
    ) -> ProcessResult:
        actual = ToolInvocation(tool=tool, args=tuple(args), timeout=timeout)
        self.invocations.append(actual)
        if not self._expectations:
            raise ToolExecutionError(f"Unexpected tool invocation: {actual}")
        expected = self._expectations[0]
        if actual != expected.invocation:
            raise ToolExecutionError(f"Expected {expected.invocation}, received {actual}")
        self._expectations.pop(0)
        for path, content in expected.file_outputs:
            path.write_bytes(content)
        return expected.result

    async def execute_plan(
        self,
        *,
        plan: ExecutionPlan,
        timeout: float | None = None,
    ) -> ProcessResult:
        del timeout
        try:
            return self._plan_results.pop(str(plan.execution_plan_id))
        except KeyError as error:
            raise ToolExecutionError(
                f"Unexpected ExecutionPlan: {plan.execution_plan_id}"
            ) from error

    def assert_expectations_met(self) -> None:
        if self._expectations:
            pending = [expectation.invocation for expectation in self._expectations]
            raise AssertionError(f"Unmet tool expectations: {pending}")
        if self._plan_results:
            raise AssertionError(f"Unmet ExecutionPlan expectations: {sorted(self._plan_results)}")


class FakeSecretService:
    def __init__(self) -> None:
        self._counter = 0
        self._values: dict[str, SensitiveValue] = {}
        self.resolutions: list[tuple[SecretRef, str]] = []

    def register(self, secret_ref: SecretRef, value: SensitiveValue | str | bytes) -> None:
        if isinstance(value, SensitiveValue):
            sensitive = SensitiveValue(value.reveal_bytes())
        elif isinstance(value, str):
            sensitive = SensitiveValue.from_text(value)
        else:
            sensitive = SensitiveValue(value)
        self._values[str(secret_ref)] = sensitive

    async def resolve(self, secret_ref: SecretRef, *, purpose: str) -> SensitiveValue:
        if not purpose:
            raise InputError("secret resolution purpose must not be empty")
        self.resolutions.append((secret_ref, purpose))
        try:
            return SensitiveValue(self._values[str(secret_ref)].reveal_bytes())
        except KeyError as error:
            raise DependencyError(f"Unknown Secret: {secret_ref}") from error

    async def store(
        self,
        *,
        value: SensitiveValue,
        secret_type: str,
        metadata: JsonObject | None = None,
    ) -> SecretRef:
        del metadata
        if not secret_type:
            raise InputError("secret type must not be empty")
        self._counter += 1
        secret_ref = SecretRef(f"secret-{self._counter:04d}")
        self._values[str(secret_ref)] = SensitiveValue(value.reveal_bytes())
        return secret_ref


class FakeEventService:
    def __init__(
        self,
        *,
        mission_ref: MissionRef,
        run_ref: CapabilityRunRef,
        clock: FakeClock,
    ) -> None:
        self._mission_ref = mission_ref
        self._run_ref = run_ref
        self._clock = clock
        self._counter = 0
        self.events: list[Event] = []

    async def progress(
        self,
        *,
        message: str,
        current: int | None = None,
        total: int | None = None,
        metadata: JsonObject | None = None,
    ) -> Event:
        if not message:
            raise InputError("progress message must not be empty")
        if current is not None and current < 0:
            raise InputError("progress current must be non-negative")
        if total is not None and total < 0:
            raise InputError("progress total must be non-negative")
        if current is not None and total is not None and current > total:
            raise InputError("progress current must not exceed total")
        self._counter += 1
        payload: JsonObject = {
            "message": message,
            "current": current,
            "total": total,
            "metadata": {} if metadata is None else metadata,
        }
        event = Event(
            event_id=EventRef(f"event-{self._counter:04d}"),
            type="capability.progress",
            timestamp=self._clock.now(),
            mission_ref=self._mission_ref,
            source_ref=self._run_ref,
            payload=payload,
        )
        self.events.append(event)
        return event


class FakeInteractionService:
    def __init__(self) -> None:
        self._responses: dict[str, InteractionResponse] = {}
        self.requests: list[InteractionRequest] = []

    def respond_with(self, response: InteractionResponse) -> None:
        self._responses[str(response.interaction_ref)] = response.model_copy(deep=True)

    async def request(self, request: InteractionRequest) -> InteractionResponse:
        self.requests.append(request.model_copy(deep=True))
        try:
            response = self._responses.pop(str(request.interaction_id))
        except KeyError as error:
            raise InteractionUnavailable(
                f"No response configured for Interaction: {request.interaction_id}"
            ) from error
        if response.run_ref != request.run_ref:
            raise InputError("Interaction response belongs to a different CapabilityRun")
        try:
            validate_interaction_response(request, response)
        except ValueError as error:
            raise InputError(str(error)) from error
        return response.model_copy(deep=True)


class FakeCheckpointService:
    def __init__(self, run_ref: CapabilityRunRef) -> None:
        self._run_ref = run_ref
        self._checkpoints: dict[str, Checkpoint] = {}

    async def save(self, checkpoint: Checkpoint) -> None:
        if checkpoint.run_ref != self._run_ref:
            raise InputError("Checkpoint belongs to a different CapabilityRun")
        self._checkpoints[str(checkpoint.checkpoint_id)] = checkpoint.model_copy(deep=True)

    async def load(self, checkpoint_ref: CheckpointRef) -> Checkpoint | None:
        checkpoint = self._checkpoints.get(str(checkpoint_ref))
        return None if checkpoint is None else checkpoint.model_copy(deep=True)


class FakeCancellationService:
    def __init__(self) -> None:
        self._requested = False

    @property
    def requested(self) -> bool:
        return self._requested

    def request(self) -> None:
        self._requested = True

    async def checkpoint(self) -> None:
        if self._requested:
            raise ExecutionCancelled("CapabilityRun cancellation requested")


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class LogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    level: LogLevel
    message: str = Field(min_length=1)
    fields: JsonObject = Field(default_factory=dict)


class FakeCapabilityLogger:
    def __init__(self) -> None:
        self.records: list[LogRecord] = []

    def _record(self, level: LogLevel, message: str, fields: dict[str, JsonValue]) -> None:
        self.records.append(LogRecord(level=level, message=message, fields=fields))

    def debug(self, message: str, **fields: JsonValue) -> None:
        self._record(LogLevel.DEBUG, message, fields)

    def info(self, message: str, **fields: JsonValue) -> None:
        self._record(LogLevel.INFO, message, fields)

    def warning(self, message: str, **fields: JsonValue) -> None:
        self._record(LogLevel.WARNING, message, fields)

    def error(self, message: str, **fields: JsonValue) -> None:
        self._record(LogLevel.ERROR, message, fields)


class FakeResourceService:
    def __init__(self, run_ref: CapabilityRunRef, clock: FakeClock) -> None:
        self._run_ref = run_ref
        self._clock = clock
        self._counter = 0
        self._resources: dict[str, ResourceDescriptor] = {}
        self._active_modes: dict[str, list[AccessMode]] = {}

    def register(self, descriptor: ResourceDescriptor) -> None:
        self._resources[str(descriptor.resource_id)] = descriptor.model_copy(deep=True)

    async def create(
        self,
        *,
        resource_type: str,
        configuration: JsonObject,
        owner_ref: DomainRef | None = None,
    ) -> ResourceDescriptor:
        self._counter += 1
        descriptor = ResourceDescriptor(
            resource_id=ResourceRef(f"resource-{self._counter:04d}"),
            resource_type=resource_type,
            provider="fake",
            state="ready",
            owner_ref=owner_ref or self._run_ref,
            created_by_run=self._run_ref,
            created_at=self._clock.now(),
            access_modes=(AccessMode.SHARED, AccessMode.EXCLUSIVE),
            lifecycle_metadata={"configuration": configuration},
        )
        self.register(descriptor)
        return descriptor

    async def get(self, resource_ref: ResourceRef) -> ResourceDescriptor:
        return self._descriptor(resource_ref).model_copy(deep=True)

    def acquire(
        self,
        resource_ref: ResourceRef,
        *,
        mode: AccessMode = AccessMode.EXCLUSIVE,
    ) -> ResourceLease:
        descriptor = self._descriptor(resource_ref)
        if mode not in descriptor.access_modes:
            raise ResourceUnavailable(f"Resource does not support {mode}: {resource_ref}")
        return _FakeResourceLease(self, resource_ref, mode)

    async def release(self, lease: ResourceLease) -> None:
        await lease.release()

    async def close(self, resource_ref: ResourceRef) -> None:
        descriptor = self._descriptor(resource_ref)
        if self._active_modes.get(str(resource_ref)):
            raise ResourceUnavailable(f"Resource is leased: {resource_ref}")
        descriptor.state = "closed"

    def _descriptor(self, resource_ref: ResourceRef) -> ResourceDescriptor:
        try:
            return self._resources[str(resource_ref)]
        except KeyError as error:
            raise ResourceUnavailable(f"Unknown Resource: {resource_ref}") from error

    def _begin_lease(self, resource_ref: ResourceRef, mode: AccessMode) -> None:
        active = self._active_modes.setdefault(str(resource_ref), [])
        conflict = mode is AccessMode.EXCLUSIVE and bool(active)
        conflict = conflict or (mode is AccessMode.SHARED and AccessMode.EXCLUSIVE in active)
        if conflict:
            raise ResourceUnavailable(f"Conflicting Resource lease: {resource_ref}")
        active.append(mode)

    def _end_lease(self, resource_ref: ResourceRef, mode: AccessMode) -> None:
        active = self._active_modes.get(str(resource_ref), [])
        if mode in active:
            active.remove(mode)


class _FakeResourceLease:
    def __init__(
        self,
        service: FakeResourceService,
        resource_ref: ResourceRef,
        mode: AccessMode,
    ) -> None:
        self._service = service
        self._resource_ref = resource_ref
        self._mode = mode
        self._entered = False

    @property
    def descriptor(self) -> ResourceDescriptor:
        return self._service._descriptor(self._resource_ref).model_copy(deep=True)

    @property
    def mode(self) -> AccessMode:
        return self._mode

    async def __aenter__(self) -> ResourceDescriptor:
        if not self._entered:
            self._service._begin_lease(self._resource_ref, self._mode)
            self._entered = True
        return self.descriptor

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback
        await self.release()

    async def release(self) -> None:
        if self._entered:
            self._service._end_lease(self._resource_ref, self._mode)
            self._entered = False


class FakeSessionService:
    def __init__(self, run_ref: CapabilityRunRef, clock: FakeClock) -> None:
        self._run_ref = run_ref
        self._clock = clock
        self._counter = 0
        self._sessions: dict[str, SessionHandle] = {}
        self._active_modes: dict[str, list[AccessMode]] = {}
        self._factories: dict[str, Callable[[JsonObject], SessionDriver]] = {}

    def register_factory(
        self,
        session_type: str,
        factory: Callable[[JsonObject], SessionDriver],
    ) -> None:
        self._factories[session_type] = factory

    def register(self, descriptor: SessionDescriptor, driver: SessionDriver) -> None:
        self._sessions[str(descriptor.session_id)] = SessionHandle(
            descriptor.model_copy(deep=True), driver
        )

    async def create(
        self,
        *,
        session_type: str,
        resource_refs: tuple[ResourceRef, ...],
        configuration: JsonObject,
        owner_ref: DomainRef | None = None,
        target_ref: DomainRef | None = None,
    ) -> SessionHandle:
        try:
            factory = self._factories[session_type]
        except KeyError as error:
            raise SessionUnavailable(f"Unknown Session type: {session_type}") from error
        self._counter += 1
        driver = factory(configuration)
        descriptor = SessionDescriptor(
            session_id=SessionRef(f"session-{self._counter:04d}"),
            session_type=session_type,
            state="ACTIVE",
            provider="fake",
            owner_ref=owner_ref or self._run_ref,
            created_by_run=self._run_ref,
            created_at=self._clock.now(),
            target_ref=target_ref,
            resource_refs=resource_refs,
            supported_operations=driver.supported_operations,
            access_modes=(AccessMode.EXCLUSIVE,),
            lifecycle_metadata={"last_activity_at": self._clock.now().isoformat()},
        )
        self.register(descriptor, driver)
        return self._handle(descriptor.session_id)

    async def get(self, session_ref: SessionRef) -> SessionHandle:
        return self._handle(session_ref)

    def acquire(
        self,
        session_ref: SessionRef,
        *,
        mode: AccessMode = AccessMode.EXCLUSIVE,
    ) -> SessionLease:
        handle = self._handle(session_ref)
        if mode not in handle.descriptor.access_modes:
            raise SessionUnavailable(f"Session does not support {mode}: {session_ref}")
        return _FakeSessionLease(self, session_ref, mode)

    async def release(self, lease: SessionLease) -> None:
        await lease.release()

    async def close(self, session_ref: SessionRef) -> None:
        handle = self._stored_handle(session_ref)
        if self._active_modes.get(str(session_ref)):
            raise SessionUnavailable(f"Session is leased: {session_ref}")
        handle.descriptor.state = "CLOSED"

    def _handle(self, session_ref: SessionRef) -> SessionHandle:
        handle = self._stored_handle(session_ref)
        return SessionHandle(handle.descriptor.model_copy(deep=True), handle.driver)

    def _stored_handle(self, session_ref: SessionRef) -> SessionHandle:
        try:
            return self._sessions[str(session_ref)]
        except KeyError as error:
            raise SessionUnavailable(f"Unknown Session: {session_ref}") from error

    def _begin_lease(self, session_ref: SessionRef, mode: AccessMode) -> None:
        handle = self._handle(session_ref)
        if handle.descriptor.state.upper() != "ACTIVE":
            raise SessionUnavailable(f"Session is not active: {session_ref}")
        active = self._active_modes.setdefault(str(session_ref), [])
        conflict = mode is AccessMode.EXCLUSIVE and bool(active)
        conflict = conflict or (mode is AccessMode.SHARED and AccessMode.EXCLUSIVE in active)
        if conflict:
            raise SessionUnavailable(f"Conflicting Session lease: {session_ref}")
        active.append(mode)

    def _end_lease(self, session_ref: SessionRef, mode: AccessMode) -> None:
        active = self._active_modes.get(str(session_ref), [])
        if mode in active:
            active.remove(mode)


class _FakeSessionLease:
    def __init__(
        self,
        service: FakeSessionService,
        session_ref: SessionRef,
        mode: AccessMode,
    ) -> None:
        self._service = service
        self._session_ref = session_ref
        self._mode = mode
        self._entered = False

    @property
    def handle(self) -> SessionHandle:
        return self._service._handle(self._session_ref)

    @property
    def mode(self) -> AccessMode:
        return self._mode

    async def __aenter__(self) -> SessionHandle:
        if not self._entered:
            self._service._begin_lease(self._session_ref, self._mode)
            self._entered = True
        return self.handle

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback
        await self.release()

    async def release(self) -> None:
        if self._entered:
            self._service._end_lease(self._session_ref, self._mode)
            self._entered = False
