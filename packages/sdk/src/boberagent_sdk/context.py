"""Read-only invocation views and the complete capability-facing context protocol."""

from __future__ import annotations

from typing import Protocol

from boberagent_contracts import (
    CapabilityId,
    CapabilityRunRef,
    JsonObject,
    MissionRef,
    OperationName,
    WorkflowRunRef,
)
from pydantic import BaseModel, ConfigDict, Field

from .services.artifacts import ArtifactService
from .services.cancellation import CancellationService
from .services.checkpoints import CheckpointService
from .services.clock import ClockService
from .services.entities import EntityReader
from .services.events import EventService
from .services.interactions import InteractionService
from .services.logging import CapabilityLogger
from .services.processes import ProcessService
from .services.resources import ResourceService
from .services.scope import ScopeService
from .services.secrets import SecretService
from .services.sessions import SessionService
from .services.workspace import WorkspaceService


class ReadOnlyContextModel(BaseModel):
    """Frozen SDK view that cannot be used to mutate platform state."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class InvocationContext(ReadOnlyContextModel):
    """Immutable metadata for exactly one CapabilityRun invocation."""

    run_id: CapabilityRunRef
    capability_id: CapabilityId
    operation: OperationName
    mission_ref: MissionRef
    parent_run_ref: CapabilityRunRef | None = None
    workflow_run_ref: WorkflowRunRef | None = None


class MissionContext(ReadOnlyContextModel):
    """Minimal capability-facing Mission view, deliberately not a Core model."""

    mission_ref: MissionRef
    name: str | None = Field(default=None, min_length=1, max_length=255)
    profile: str | None = Field(default=None, min_length=1, max_length=255)
    objectives: tuple[str, ...] = ()
    metadata: JsonObject = Field(default_factory=dict)


class ExecutionContext(Protocol):
    """Complete supported bridge from capability code to platform services."""

    @property
    def invocation(self) -> InvocationContext: ...

    @property
    def mission(self) -> MissionContext: ...

    @property
    def scope(self) -> ScopeService: ...

    @property
    def entities(self) -> EntityReader: ...

    @property
    def processes(self) -> ProcessService: ...

    @property
    def workspace(self) -> WorkspaceService: ...

    @property
    def resources(self) -> ResourceService: ...

    @property
    def sessions(self) -> SessionService: ...

    @property
    def artifacts(self) -> ArtifactService: ...

    @property
    def secrets(self) -> SecretService: ...

    @property
    def interactions(self) -> InteractionService: ...

    @property
    def checkpoints(self) -> CheckpointService: ...

    @property
    def events(self) -> EventService: ...

    @property
    def logger(self) -> CapabilityLogger: ...

    @property
    def cancellation(self) -> CancellationService: ...

    @property
    def clock(self) -> ClockService: ...
