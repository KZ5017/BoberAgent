"""Durable browser Resource/Session lifecycle and recovery tests."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_contracts import (
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    ResourceRef,
    SessionRef,
)
from boberagent_execution_node import ToolConfiguration
from boberagent_execution_node.browser import BrowserRuntimeManager
from boberagent_execution_node.persistence import (
    ResourceRuntimeState,
    RunRecord,
    RuntimeDatabase,
    RuntimeStore,
    SessionRuntimeState,
)
from boberagent_execution_node.persistence.migrations import upgrade_database
from boberagent_execution_node.tools import ToolRegistry
from boberagent_sdk import BrowserInspection, BrowserPageState, SessionUnavailable

NOW = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)
RUN_REF = CapabilityRunRef("run-browser-manager")


class FakeBrowserSession:
    def __init__(self) -> None:
        self.closed = False

    @property
    def supported_operations(self) -> tuple[str, ...]:
        return ("navigate", "inspect")

    async def navigate(
        self,
        url: str,
        *,
        allowed_hosts: tuple[str, ...],
        timeout: float | None = None,
    ) -> BrowserPageState:
        del allowed_hosts, timeout
        return BrowserPageState(final_url=url, title="Fake", status_code=200)

    async def inspect(self, *, max_html_bytes: int) -> BrowserInspection:
        del max_html_bytes
        return BrowserInspection(
            page=BrowserPageState(final_url="http://browser.test/", title="Fake"),
            html=b"<html></html>",
        )

    async def close(self) -> None:
        self.closed = True


class FakeBrowserRuntime:
    def __init__(self) -> None:
        self.sessions: list[FakeBrowserSession] = []
        self.closed = False

    async def create_session(self) -> FakeBrowserSession:
        session = FakeBrowserSession()
        self.sessions.append(session)
        return session

    async def close(self) -> None:
        self.closed = True
        for session in self.sessions:
            await session.close()


class FakeBrowserBackend:
    def __init__(self) -> None:
        self.runtimes: list[FakeBrowserRuntime] = []

    async def launch(self, *, executable_path: Path, headless: bool) -> FakeBrowserRuntime:
        assert executable_path == Path(sys.executable).resolve()
        assert headless
        runtime = FakeBrowserRuntime()
        self.runtimes.append(runtime)
        return runtime


async def _tools() -> ToolRegistry:
    tools = ToolRegistry()
    tools.register("chromium", ToolConfiguration(executable=sys.executable))
    await tools.refresh()
    return tools


def _store(path: Path) -> tuple[RuntimeDatabase, RuntimeStore]:
    database = RuntimeDatabase(path)
    upgrade_database(database)
    store = RuntimeStore(database)
    if store.get_run(RUN_REF) is None:
        store.add_run(
            RunRecord(
                run_ref=RUN_REF,
                mission_ref=MissionRef("mission-browser-manager"),
                capability_id="browser.interaction",
                operation="open",
                status=CapabilityRunStatus.RUNNING,
                created_at=NOW,
            )
        )
    return database, store


def test_browser_resource_and_session_lifecycle_is_durable_and_idempotent(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database, store = _store(tmp_path / "runtime.sqlite3")
        backend = FakeBrowserBackend()
        manager = BrowserRuntimeManager(
            store=store,
            tools=await _tools(),
            backend=backend,
            clock=lambda: NOW,
        )
        resources = manager.resource_service(RUN_REF)
        sessions = manager.session_service(RUN_REF)
        resource = await resources.create(
            resource_type="browser_process",
            configuration={"headless": True},
            owner_ref=MissionRef("mission-browser-manager"),
        )
        handle = await sessions.create(
            session_type="browser",
            resource_refs=(resource.resource_id,),
            configuration={},
            owner_ref=MissionRef("mission-browser-manager"),
        )
        assert resource.state == ResourceRuntimeState.READY
        assert handle.descriptor.state == SessionRuntimeState.ACTIVE
        assert store.runtime_resource_count() == store.runtime_session_count() == 1

        async with sessions.acquire(handle.descriptor.session_id) as leased:
            assert leased.driver.supported_operations == ("navigate", "inspect")
        store.update_resource_state(resource.resource_id, ResourceRuntimeState.FAILED, NOW)
        with pytest.raises(SessionUnavailable, match="backing browser Resource is not ready"):
            sessions.acquire(handle.descriptor.session_id)
        store.update_resource_state(resource.resource_id, ResourceRuntimeState.READY, NOW)
        await sessions.close(handle.descriptor.session_id)
        await sessions.close(handle.descriptor.session_id)
        assert (await sessions.get(handle.descriptor.session_id)).descriptor.state == "CLOSED"
        with pytest.raises(SessionUnavailable, match="not active"):
            sessions.acquire(handle.descriptor.session_id)

        await resources.close(resource.resource_id)
        await resources.close(resource.resource_id)
        assert (await resources.get(resource.resource_id)).state == "CLOSED"
        assert backend.runtimes[0].closed
        assert backend.runtimes[0].sessions[0].closed
        database.close()

        reopened = RuntimeDatabase(tmp_path / "runtime.sqlite3")
        try:
            reopened_store = RuntimeStore(reopened)
            assert reopened_store.get_resource(resource.resource_id) is not None
            assert reopened_store.get_session(handle.descriptor.session_id) is not None
        finally:
            reopened.close()

    asyncio.run(scenario())


def test_restart_marks_non_restorable_browser_state_lost(tmp_path: Path) -> None:
    async def scenario() -> tuple[ResourceRef, SessionRef, FakeBrowserRuntime]:
        database, store = _store(tmp_path / "lost.sqlite3")
        backend = FakeBrowserBackend()
        manager = BrowserRuntimeManager(
            store=store,
            tools=await _tools(),
            backend=backend,
            clock=lambda: NOW,
        )
        resource = await manager.resource_service(RUN_REF).create(
            resource_type="browser_process", configuration={"headless": True}
        )
        session = await manager.session_service(RUN_REF).create(
            session_type="browser",
            resource_refs=(resource.resource_id,),
            configuration={},
        )
        database.close()  # Simulate process loss: no graceful manager shutdown.
        return resource.resource_id, session.descriptor.session_id, backend.runtimes[0]

    resource_ref, session_ref, abandoned_runtime = asyncio.run(scenario())
    reopened = RuntimeDatabase(tmp_path / "lost.sqlite3")
    try:
        store = RuntimeStore(reopened)
        assert store.recover_non_restorable_browser_state(NOW) == (1, 1)
        resource = store.get_resource(resource_ref)
        session = store.get_session(session_ref)
        assert resource is not None and resource.descriptor.state == "LOST"
        assert session is not None and session.descriptor.state == "LOST"
        assert store.recover_non_restorable_browser_state(NOW) == (0, 0)
    finally:
        reopened.close()
        asyncio.run(abandoned_runtime.close())
