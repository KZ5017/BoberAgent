"""Managed runtime-local workspace abstractions."""

from enum import StrEnum
from pathlib import Path
from typing import Protocol

from boberagent_contracts import CapabilityRunRef, DomainRef


class WorkspaceRef(DomainRef):
    """Logical identity for a runtime-local managed workspace."""


class WorkspaceIsolation(StrEnum):
    RUN = "run"
    RESOURCE = "resource"
    MISSION = "mission"


class Workspace:
    """Read-only handle whose path is local and never a durable identity."""

    __slots__ = ("_isolation", "_owner_ref", "_path", "_purpose", "_workspace_ref")

    def __init__(
        self,
        *,
        workspace_ref: WorkspaceRef,
        purpose: str,
        isolation: WorkspaceIsolation,
        owner_ref: DomainRef | CapabilityRunRef,
        path: Path,
    ) -> None:
        self._workspace_ref = workspace_ref
        self._purpose = purpose
        self._isolation = isolation
        self._owner_ref = owner_ref
        self._path = path

    @property
    def workspace_ref(self) -> WorkspaceRef:
        return self._workspace_ref

    @property
    def purpose(self) -> str:
        return self._purpose

    @property
    def isolation(self) -> WorkspaceIsolation:
        return self._isolation

    @property
    def owner_ref(self) -> DomainRef:
        return self._owner_ref

    @property
    def path(self) -> Path:
        return self._path


class WorkspaceService(Protocol):
    async def create(
        self,
        *,
        purpose: str,
        isolation: WorkspaceIsolation = WorkspaceIsolation.RUN,
        owner_ref: DomainRef | None = None,
    ) -> Workspace: ...

    async def cleanup(self, workspace_ref: WorkspaceRef) -> None: ...
