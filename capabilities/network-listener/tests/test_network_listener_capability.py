"""SDK-only tests for the production ``network.listener`` capability."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_capability_network_listener import (
    CloseListenerInput,
    CloseSessionInput,
    InspectListenerInput,
    NetworkListenerCapability,
    OpenListenerInput,
    ReceiveInput,
    SendInput,
)
from boberagent_contracts import (
    AccessMode,
    CapabilityOutcomeCategory,
    CapabilityRunRef,
    MissionRef,
    ResourceDescriptor,
    ResourceRef,
    SessionDescriptor,
    SessionRef,
)
from boberagent_execution_node.capabilities import CapabilityManifest
from boberagent_sdk import ByteStreamRead, ScopeViolation
from boberagent_sdk.testing import FakeExecutionContext
from pydantic import ValidationError

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
RESOURCE_REF = ResourceRef("resource-listener-test")
SESSION_REF = SessionRef("session-listener-test")


class FakeByteStream:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    @property
    def supported_operations(self) -> tuple[str, ...]:
        return ("receive", "send")

    async def receive(self, *, max_bytes: int, timeout: float) -> ByteStreamRead:
        assert max_bytes == 32
        assert timeout == 2
        return ByteStreamRead(data=b"incoming\x00bytes")

    async def send(self, data: bytes, *, timeout: float) -> int:
        assert timeout == 2
        self.sent.append(bytes(data))
        return len(data)


def _context() -> tuple[FakeExecutionContext, FakeByteStream]:
    context = FakeExecutionContext()
    context.scope.allow_address("127.0.0.1")
    context.resources.register(
        ResourceDescriptor(
            resource_id=RESOURCE_REF,
            resource_type="tcp_listener",
            provider="asyncio.tcp",
            state="READY",
            owner_ref=context.mission.mission_ref,
            created_by_run=context.invocation.run_id,
            created_at=NOW,
            access_modes=(AccessMode.EXCLUSIVE,),
            lifecycle_metadata={
                "bound_address": "127.0.0.1",
                "bound_port": 4444,
                "active_sessions": 1,
            },
        )
    )
    driver = FakeByteStream()
    context.sessions.register(
        SessionDescriptor(
            session_id=SESSION_REF,
            session_type="tcp_stream",
            state="ACTIVE",
            provider="asyncio.tcp",
            owner_ref=context.mission.mission_ref,
            created_by_run=context.invocation.run_id,
            created_at=NOW,
            resource_refs=(RESOURCE_REF,),
            supported_operations=("receive", "send"),
            access_modes=(AccessMode.EXCLUSIVE,),
            lifecycle_metadata={
                "remote_address": "127.0.0.1",
                "remote_port": 54321,
                "local_address": "127.0.0.1",
                "local_port": 4444,
            },
        ),
        driver,
    )
    return context, driver


def test_manifest_is_static_and_declares_semantic_listener_operations() -> None:
    manifest_path = Path(__file__).parents[1] / "capability.json"
    manifest = CapabilityManifest.model_validate(json.loads(manifest_path.read_text()))

    assert manifest.definition.capability_id == "network.listener"
    assert {operation.name for operation in manifest.definition.operations} == {
        "open",
        "inspect",
        "receive",
        "send",
        "close_session",
        "close_listener",
    }
    assert manifest.definition.dependencies == ()


def test_open_checks_bind_and_peer_scope_before_creating_listener() -> None:
    async def scenario() -> None:
        capability = NetworkListenerCapability()
        denied = FakeExecutionContext()
        denied.scope.allow_address("127.0.0.1")
        with pytest.raises(ScopeViolation):
            await capability.execute(
                "open",
                denied,
                OpenListenerInput(
                    bind_address="127.0.0.1",
                    allowed_remote_addresses=("192.0.2.10",),
                ),
            )
        denied.close()

        context = FakeExecutionContext()
        context.scope.allow_address("127.0.0.1")
        async with context:
            result = await capability.execute(
                "open",
                context,
                OpenListenerInput(
                    bind_address="127.0.0.1",
                    allowed_remote_addresses=("127.0.0.1",),
                    max_sessions=2,
                ),
            )
            assert result.outcome.category is CapabilityOutcomeCategory.SUCCESS
            assert result.outcome.code == "LISTENER_OPENED"
            assert len(result.resources) == 1
            assert result.sessions == ()

    asyncio.run(scenario())


def test_inspect_receive_send_and_idempotent_close_use_semantic_sdk_services() -> None:
    async def scenario() -> None:
        context, driver = _context()
        capability = NetworkListenerCapability()
        async with context:
            inspected = await capability.execute(
                "inspect", context, InspectListenerInput(resource_ref=RESOURCE_REF)
            )
            assert inspected.outcome.details["bound_port"] == 4444

            received = await capability.execute(
                "receive",
                context,
                ReceiveInput(session_ref=SESSION_REF, max_bytes=32, timeout_seconds=2),
            )
            encoded_received = received.outcome.details["payload_base64"]
            assert isinstance(encoded_received, str)
            assert base64.b64decode(encoded_received) == b"incoming\x00bytes"
            assert received.outcome.details["bytes_received"] == 14

            encoded = base64.b64encode(b"outgoing\x00bytes").decode("ascii")
            sent = await capability.execute(
                "send",
                context,
                SendInput(
                    session_ref=SESSION_REF,
                    payload_base64=encoded,
                    timeout_seconds=2,
                ),
            )
            assert sent.outcome.details["bytes_sent"] == 14
            assert driver.sent == [b"outgoing\x00bytes"]

            closed = await capability.execute(
                "close_session", context, CloseSessionInput(session_ref=SESSION_REF)
            )
            closed_again = await capability.execute(
                "close_session", context, CloseSessionInput(session_ref=SESSION_REF)
            )
            assert closed.outcome.code == "STREAM_SESSION_CLOSED"
            assert closed_again.outcome.code == "STREAM_SESSION_ALREADY_CLOSED"

            listener_closed = await capability.execute(
                "close_listener", context, CloseListenerInput(resource_ref=RESOURCE_REF)
            )
            listener_closed_again = await capability.execute(
                "close_listener", context, CloseListenerInput(resource_ref=RESOURCE_REF)
            )
            assert listener_closed.outcome.code == "LISTENER_CLOSED"
            assert listener_closed_again.outcome.code == "LISTENER_ALREADY_CLOSED"

    asyncio.run(scenario())


def test_inputs_reject_wildcards_unbounded_values_and_noncanonical_base64() -> None:
    with pytest.raises(ValidationError, match="wildcard"):
        OpenListenerInput(bind_address="0.0.0.0", allowed_remote_addresses=("127.0.0.1",))
    with pytest.raises(ValidationError):
        ReceiveInput(session_ref=SESSION_REF, max_bytes=65537)
    with pytest.raises(ValidationError, match="base64"):
        SendInput(session_ref=SESSION_REF, payload_base64="!!!!")
    with pytest.raises(ValidationError):
        SendInput(
            session_ref=SESSION_REF,
            payload_base64=base64.b64encode(b"x" * 65537).decode("ascii"),
        )


def test_session_cross_mission_access_is_rejected() -> None:
    async def scenario() -> None:
        context, _driver = _context()
        foreign = SessionDescriptor(
            session_id=SessionRef("session-foreign-mission"),
            session_type="tcp_stream",
            state="ACTIVE",
            provider="asyncio.tcp",
            owner_ref=MissionRef("mission-foreign"),
            created_by_run=CapabilityRunRef("run-foreign"),
            created_at=NOW,
            resource_refs=(RESOURCE_REF,),
            supported_operations=("receive", "send"),
            access_modes=(AccessMode.EXCLUSIVE,),
            lifecycle_metadata={"remote_address": "127.0.0.1"},
        )
        context.sessions.register(foreign, FakeByteStream())
        async with context:
            from boberagent_sdk import SessionUnavailable

            with pytest.raises(SessionUnavailable, match="does not belong"):
                await NetworkListenerCapability().execute(
                    "receive",
                    context,
                    ReceiveInput(session_ref=foreign.session_id),
                )

    asyncio.run(scenario())
