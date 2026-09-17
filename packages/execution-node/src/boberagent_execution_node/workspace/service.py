"""Persistent managed workspaces constrained beneath the configured root."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

from boberagent_contracts import CapabilityRunRef, DomainRef
from boberagent_sdk import Workspace, WorkspaceIsolation, WorkspaceRef

from boberagent_execution_node.persistence import (
    RuntimeStore,
    WorkspaceRecord,
    WorkspaceState,
)


class ManagedWorkspaceService:
    def __init__(
        self,
        *,
        root: Path,
        store: RuntimeStore,
        run_ref: CapabilityRunRef,
        clock: Callable[[], datetime],
    ) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._store = store
        self._run_ref = run_ref
        self._clock = clock

    async def create(
        self,
        *,
        purpose: str,
        isolation: WorkspaceIsolation = WorkspaceIsolation.RUN,
        owner_ref: DomainRef | None = None,
    ) -> Workspace:
        if not purpose or len(purpose) > 255:
            raise ValueError("workspace purpose must contain 1-255 characters")
        workspace_ref = WorkspaceRef(f"workspace-{uuid4()}")
        path = (self._root / str(workspace_ref)).resolve()
        _assert_managed_path(self._root, path)
        path.mkdir(mode=0o700)
        selected_owner = owner_ref or self._run_ref
        self._store.add_workspace(
            WorkspaceRecord(
                workspace_ref=workspace_ref,
                owner_ref=str(selected_owner),
                purpose=purpose,
                isolation=isolation,
                local_path=str(path),
                state=WorkspaceState.ACTIVE,
                created_at=self._clock(),
            )
        )
        return Workspace(
            workspace_ref=workspace_ref,
            purpose=purpose,
            isolation=isolation,
            owner_ref=selected_owner,
            path=path,
        )

    async def get(self, workspace_ref: WorkspaceRef) -> Workspace:
        record = self._store.get_workspace(workspace_ref)
        if record is None or record.state is WorkspaceState.REMOVED:
            raise KeyError(f"unknown active Workspace: {workspace_ref}")
        path = Path(record.local_path).resolve()
        _assert_managed_path(self._root, path)
        return Workspace(
            workspace_ref=record.workspace_ref,
            purpose=record.purpose,
            isolation=record.isolation,
            owner_ref=DomainRef(record.owner_ref),
            path=path,
        )

    async def cleanup(self, workspace_ref: WorkspaceRef) -> None:
        workspace = await self.get(workspace_ref)
        self._store.set_workspace_state(workspace_ref, WorkspaceState.CLEANUP_PENDING)
        if workspace.path.exists():
            rmtree(workspace.path)
        self._store.set_workspace_state(workspace_ref, WorkspaceState.REMOVED)


def _assert_managed_path(root: Path, path: Path) -> None:
    if path == root or not path.is_relative_to(root):
        raise ValueError("workspace path escapes configured managed root")
