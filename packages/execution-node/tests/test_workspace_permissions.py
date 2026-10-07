"""Production workspace composition must satisfy unchanged E5 storage trust."""

import asyncio
import os
import stat
from pathlib import Path

import pytest
from boberagent_contracts import CapabilityRunRef, ResourceRef
from boberagent_execution_node import ExecutionNode, NodeConfiguration
from boberagent_execution_node.lifecycle import NodeLifecycleState
from boberagent_execution_node.persistence import RuntimeDatabase, RuntimeStore
from boberagent_execution_node.persistence.migrations import upgrade_database
from boberagent_execution_node.preparation.environment_storage import EnvironmentStorage
from boberagent_execution_node.preparation.service import NodePreparationService
from boberagent_execution_node.workspace import ManagedWorkspaceService
from boberagent_execution_node.workspace.directories import WorkspaceDirectoryError
from plan_test_fixtures import NOW


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.parametrize("mask", [0o000, 0o002, 0o022, 0o077])
def test_production_creation_is_private_under_permissive_umask(tmp_path: Path, mask: int) -> None:
    configuration = NodeConfiguration.for_runtime_directory(tmp_path / "new-parent/node")
    previous = os.umask(mask)
    try:
        configuration.prepare_directories()
        assert mode(tmp_path / "new-parent") == 0o700
        assert mode(configuration.runtime_directory) == 0o700
        assert mode(configuration.workspace_root) == 0o700
        storage = EnvironmentStorage(configuration.workspace_root / "python-environments")
        assert not storage.root.exists()  # Configuration is not a constructor.
        owned = storage.reserve(ResourceRef("resource-private-workspace"))
        assert mode(storage.root) == mode(owned) == 0o700
    finally:
        os.umask(previous)


@pytest.mark.parametrize("bad_component", ["runtime", "workspace", "ancestor"])
def test_existing_untrusted_ancestors_fail_without_repair(
    tmp_path: Path, bad_component: str
) -> None:
    configuration = NodeConfiguration.for_runtime_directory(tmp_path / "parent/node")
    configuration.workspace_root.mkdir(parents=True, mode=0o700)
    # Test setup deliberately creates trust-compatible parents first.
    (tmp_path / "parent").chmod(0o700)
    configuration.runtime_directory.chmod(0o700)
    bad = {
        "runtime": configuration.runtime_directory,
        "workspace": configuration.workspace_root,
        "ancestor": tmp_path / "parent",
    }[bad_component]
    bad.chmod(0o775)
    with pytest.raises(WorkspaceDirectoryError, match=r"^WORKSPACE_STORAGE_UNTRUSTED$"):
        configuration.prepare_directories()
    storage = EnvironmentStorage(configuration.workspace_root / "python-environments")
    with pytest.raises(ValueError, match="untrusted storage ancestor"):
        storage.reserve(ResourceRef("resource-denied-workspace"))
    assert mode(bad) == 0o775
    assert not storage.root.exists()


def test_symlink_workspace_is_not_followed(tmp_path: Path) -> None:
    configuration = NodeConfiguration.for_runtime_directory(tmp_path / "node")
    configuration.runtime_directory.mkdir(mode=0o700)
    target = tmp_path / "outside"
    target.mkdir(mode=0o700)
    configuration.workspace_root.symlink_to(target, target_is_directory=True)
    with pytest.raises(WorkspaceDirectoryError):
        configuration.prepare_directories()
    assert list(target.iterdir()) == []


def test_trusted_existing_runtime_modes_are_preserved(tmp_path: Path) -> None:
    configuration = NodeConfiguration.for_runtime_directory(tmp_path / "node")
    configuration.workspace_root.mkdir(parents=True)
    configuration.runtime_directory.chmod(0o755)
    configuration.workspace_root.chmod(0o755)
    configuration.prepare_directories()
    assert mode(configuration.runtime_directory) == mode(configuration.workspace_root) == 0o755


def test_sdk_workspace_and_e4_intermediate_root_are_private(tmp_path: Path) -> None:
    database = RuntimeDatabase(tmp_path / "runtime.sqlite3")
    upgrade_database(database)
    previous = os.umask(0o002)
    try:
        workspace_root = tmp_path / "workspaces"
        service = ManagedWorkspaceService(
            root=workspace_root,
            store=RuntimeStore(database),
            run_ref=CapabilityRunRef("run-workspace-mode"),
            clock=lambda: NOW,
        )
        workspace = asyncio.run(service.create(purpose="mode-check"))
        assert mode(workspace_root) == mode(workspace.path) == 0o700
        preparation = NodePreparationService(
            database, tmp_path / "imports", "node-test", workspace_root
        )
        assert not (workspace_root / "preparation-source").exists()
        preparation._ensure_materialization_dirs()
        for name in ("", "staging", "published", "quarantine"):
            assert mode(workspace_root / "preparation-source" / name) == 0o700
        assert not (workspace_root / "python-environments").exists()
        source_root = workspace_root / "preparation-source"
        source_root.chmod(0o775)
        with pytest.raises(WorkspaceDirectoryError):
            preparation._ensure_materialization_dirs()
        assert mode(source_root) == 0o775
        workspace_root.chmod(0o775)
        with pytest.raises(WorkspaceDirectoryError):
            ManagedWorkspaceService(
                root=workspace_root,
                store=RuntimeStore(database),
                run_ref=CapabilityRunRef("run-untrusted-workspace"),
                clock=lambda: NOW,
            )
        assert mode(workspace_root) == 0o775
    finally:
        os.umask(previous)
        database.close()


def test_node_startup_does_not_create_environment_storage(tmp_path: Path) -> None:
    async def scenario() -> None:
        configuration = NodeConfiguration.for_runtime_directory(tmp_path / "node")
        node = ExecutionNode(configuration)
        previous = os.umask(0o002)
        try:
            await node.initialize()
            assert (
                mode(configuration.runtime_directory) == mode(configuration.workspace_root) == 0o700
            )
            assert not (configuration.workspace_root / "python-environments").exists()
            assert not (configuration.workspace_root / "preparation-source").exists()
        finally:
            os.umask(previous)
            await node.shutdown()

    asyncio.run(scenario())


def test_untrusted_workspace_fails_at_composition_not_generic_constructor_failure(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        configuration = NodeConfiguration.for_runtime_directory(tmp_path / "node")
        configuration.runtime_directory.mkdir(mode=0o700)
        configuration.workspace_root.mkdir(mode=0o700)
        configuration.workspace_root.chmod(0o775)
        node = ExecutionNode(configuration)
        try:
            with pytest.raises(WorkspaceDirectoryError) as rejected:
                await node.initialize()
            assert rejected.value.code == "WORKSPACE_STORAGE_UNTRUSTED"
            assert node.lifecycle.state is NodeLifecycleState.FAILED
            assert mode(configuration.workspace_root) == 0o775
            assert not configuration.database_path.exists()
            assert not (configuration.workspace_root / "python-environments").exists()
        finally:
            await node.shutdown()

    asyncio.run(scenario())
