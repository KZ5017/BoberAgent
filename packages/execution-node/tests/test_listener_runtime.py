"""Real loopback tests for the Node-owned TCP listener runtime."""

from __future__ import annotations

import asyncio
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
from boberagent_execution_node import ExecutionNode, NodeConfiguration
from boberagent_execution_node.events import EventOutbox
from boberagent_execution_node.listener import ListenerRuntimeManager
from boberagent_execution_node.persistence import (
    ResourceRuntimeState,
    RunRecord,
    RuntimeDatabase,
    RuntimeStore,
    SessionRuntimeState,
)
from boberagent_execution_node.persistence.migrations import upgrade_database
from boberagent_sdk import ByteStreamSession, ExecutionTimeout, ResourceUnavailable

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
RUN_REF = CapabilityRunRef("run-listener-runtime")
MISSION_REF = MissionRef("mission-listener-runtime")


def _store(path: Path) -> tuple[RuntimeDatabase, RuntimeStore]:
    database = RuntimeDatabase(path)
    upgrade_database(database)
    store = RuntimeStore(database)
    if store.get_run(RUN_REF) is None:
        store.add_run(
            RunRecord(
                run_ref=RUN_REF,
                mission_ref=MISSION_REF,
                capability_id="network.listener",
                operation="open",
                status=CapabilityRunStatus.RUNNING,
                created_at=NOW,
            )
        )
    return database, store


async def _wait_for_sessions(store: RuntimeStore, count: int) -> None:
    for _ in range(100):
        if len(store.list_sessions()) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"expected {count} accepted Sessions")


def test_listener_accepts_multiple_sessions_and_moves_bounded_binary_bytes(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database, store = _store(tmp_path / "runtime.sqlite3")
        manager = ListenerRuntimeManager(
            store=store,
            event_outbox=EventOutbox(store),
            clock=lambda: NOW,
        )
        try:
            resource = await manager.resource_service(RUN_REF).create(
                resource_type="tcp_listener",
                configuration={
                    "bind_address": "127.0.0.1",
                    "port": 0,
                    "allowed_remote_addresses": ["127.0.0.1"],
                    "max_sessions": 2,
                },
                owner_ref=MISSION_REF,
            )
            assert resource.state == ResourceRuntimeState.READY
            port = resource.lifecycle_metadata["bound_port"]
            assert isinstance(port, int) and port > 0

            first_reader, first_writer = await asyncio.open_connection("127.0.0.1", port)
            second_reader, second_writer = await asyncio.open_connection("127.0.0.1", port)
            await _wait_for_sessions(store, 2)
            sessions = store.list_sessions_for_resource(resource.resource_id)
            assert len({session.descriptor.session_id for session in sessions}) == 2
            assert all(
                session.descriptor.state == SessionRuntimeState.ACTIVE for session in sessions
            )
            assert [record.event.type for record in store.pending_events()].count(
                "session.created"
            ) == 2

            first_local = first_writer.get_extra_info("sockname")
            assert isinstance(first_local, tuple)
            selected = next(
                session.descriptor.session_id
                for session in sessions
                if session.descriptor.lifecycle_metadata["remote_port"] == first_local[1]
            )
            async with manager.session_service(RUN_REF).acquire(selected) as handle:
                assert isinstance(handle.driver, ByteStreamSession)
                with pytest.raises(ExecutionTimeout, match="receive timed out"):
                    await handle.driver.receive(max_bytes=1, timeout=0.01)
            first_writer.write(b"hello\x00listener")
            await first_writer.drain()
            async with manager.session_service(RUN_REF).acquire(selected) as handle:
                assert isinstance(handle.driver, ByteStreamSession)
                incoming = await handle.driver.receive(max_bytes=64, timeout=1)
                assert incoming.data == b"hello\x00listener"
                assert not incoming.eof
                assert await handle.driver.send(b"reply\x00bytes", timeout=1) == 11
            assert await first_reader.readexactly(11) == b"reply\x00bytes"

            await manager.session_service(RUN_REF).close(selected)
            await manager.session_service(RUN_REF).close(selected)
            closed_session = store.get_session(selected)
            assert closed_session is not None
            assert closed_session.descriptor.state == SessionRuntimeState.CLOSED
            assert await asyncio.wait_for(first_reader.read(), timeout=1) == b""
            assert manager.active_listener_count == 1

            second_writer.close()
            await asyncio.wait_for(second_writer.wait_closed(), timeout=1)
            await manager.resource_service(RUN_REF).close(resource.resource_id)
            await manager.resource_service(RUN_REF).close(resource.resource_id)
            closed_resource = store.get_resource(resource.resource_id)
            assert closed_resource is not None
            assert closed_resource.descriptor.state == ResourceRuntimeState.CLOSED
            assert manager.active_listener_count == 0
            assert manager.active_session_count == 0
            assert manager.active_accept_task_count == 0
            first_writer.close()
            await asyncio.wait_for(first_writer.wait_closed(), timeout=1)
            del second_reader
        finally:
            await manager.shutdown()
            database.close()

    asyncio.run(scenario())


def test_listener_capacity_bind_conflict_and_restart_recovery(tmp_path: Path) -> None:
    configuration = NodeConfiguration.for_runtime_directory(
        tmp_path / "recovery-node",
        configured_node_id="node-listener-recovery",
    )
    configuration.prepare_directories()
    database_path = configuration.database_path

    async def create_interrupted_state() -> tuple[ResourceRef, SessionRef]:
        database, store = _store(database_path)
        manager = ListenerRuntimeManager(
            store=store,
            event_outbox=EventOutbox(store),
            clock=lambda: NOW,
        )
        resource = await manager.resource_service(RUN_REF).create(
            resource_type="tcp_listener",
            configuration={
                "bind_address": "127.0.0.1",
                "port": 0,
                "allowed_remote_addresses": ["127.0.0.1"],
                "max_sessions": 1,
            },
        )
        port = resource.lifecycle_metadata["bound_port"]
        assert isinstance(port, int)
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await _wait_for_sessions(store, 1)
        rejected_reader, rejected_writer = await asyncio.open_connection("127.0.0.1", port)
        assert await asyncio.wait_for(rejected_reader.read(), timeout=1) == b""
        rejected_writer.close()
        await rejected_writer.wait_closed()
        assert len(store.list_sessions_for_resource(resource.resource_id)) == 1
        assert any(
            record.event.type == "session.rejected"
            and record.event.payload["reason"] == "capacity_reached"
            for record in store.pending_events()
        )
        with pytest.raises(ResourceUnavailable, match="failed to bind"):
            await manager.resource_service(RUN_REF).create(
                resource_type="tcp_listener",
                configuration={
                    "bind_address": "127.0.0.1",
                    "port": port,
                    "allowed_remote_addresses": ["127.0.0.1"],
                },
            )
        session_ref = store.list_sessions_for_resource(resource.resource_id)[
            0
        ].descriptor.session_id
        writer.close()
        await writer.wait_closed()
        await manager.shutdown()
        # Recreate the exact durable state a process loss leaves behind without
        # leaking sockets or event-loop-owned handles into the next test loop.
        store.update_resource_state(resource.resource_id, ResourceRuntimeState.READY, NOW)
        store.update_session_state(session_ref, SessionRuntimeState.ACTIVE, NOW)
        database.close()
        return resource.resource_id, session_ref

    resource_ref, session_ref = asyncio.run(create_interrupted_state())

    async def restart_node() -> None:
        restarted = ExecutionNode(configuration)
        health = await restarted.initialize()
        assert restarted.store is not None
        store = restarted.store
        resource = store.get_resource(resource_ref)
        session = store.get_session(session_ref)
        assert resource is not None and resource.descriptor.state == ResourceRuntimeState.LOST
        assert session is not None and session.descriptor.state == SessionRuntimeState.LOST
        assert store.recover_non_restorable_listener_state(NOW) == (0, 0)
        assert any("TCP Listener" in reason for reason in health.degraded_reasons)
        await restarted.shutdown()

    asyncio.run(restart_node())


def test_listener_rejects_wildcard_binding() -> None:
    from boberagent_execution_node.listener import ListenerResourceConfiguration

    with pytest.raises(ValueError, match="wildcard"):
        ListenerResourceConfiguration(
            bind_address="0.0.0.0",
            port=4444,
            allowed_remote_addresses=("127.0.0.1",),
        )


def test_listener_rejects_unauthorized_peer_without_creating_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        database, store = _store(tmp_path / "unauthorized.sqlite3")
        manager = ListenerRuntimeManager(
            store=store,
            event_outbox=EventOutbox(store),
            clock=lambda: NOW,
        )
        try:
            resource = await manager.resource_service(RUN_REF).create(
                resource_type="tcp_listener",
                configuration={
                    "bind_address": "127.0.0.1",
                    "port": 0,
                    "allowed_remote_addresses": ["127.0.0.2"],
                },
            )
            port = resource.lifecycle_metadata["bound_port"]
            assert isinstance(port, int)
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            assert await asyncio.wait_for(reader.read(), timeout=1) == b""
            writer.close()
            await writer.wait_closed()
            assert store.list_sessions_for_resource(resource.resource_id) == ()
            rejection = next(
                record.event
                for record in store.pending_events()
                if record.event.type == "session.rejected"
            )
            assert rejection.payload["reason"] == "remote_not_authorized"
            assert rejection.payload["remote_address"] == "127.0.0.1"
        finally:
            await manager.shutdown()
            database.close()

    asyncio.run(scenario())
