"""Manual WSL Core to Kali Node incoming TCP Session smoke test."""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import uuid
from pathlib import Path

from boberagent_contracts import (
    CapabilityInvocation,
    CapabilityResult,
    CapabilityRunRef,
    JsonObject,
    MissionRef,
    ResourceRef,
    SessionRef,
)
from boberagent_core import CoreDatabase, CoreTransportClient, CoreTransportReceiver, DatabaseConfig
from boberagent_core.persistence.migrations import upgrade_database
from boberagent_transport import InvocationDelivery, MissionProjection
from boberagent_transport_mcp import McpClientConfiguration, McpTransport
from pydantic import SecretStr


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prove network.listener and incoming Session lifecycle across real MCP"
    )
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--core-runtime-directory", type=Path, required=True)
    parser.add_argument("--bind-address", required=True)
    parser.add_argument("--allowed-peer-address", required=True)
    parser.add_argument("--port", type=int, default=45873)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--allow-insecure-remote-transport", action="store_true")
    parser.add_argument("--token-environment-variable", default="BOBERAGENT_MCP_TOKEN")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser


class ListenerSmoke:
    def __init__(
        self,
        *,
        transport: McpTransport,
        client: CoreTransportClient,
        receiver: CoreTransportReceiver,
        node_id: str,
        mission_ref: MissionRef,
        allowed_addresses: tuple[str, ...],
        timeout_seconds: float,
    ) -> None:
        self._transport = transport
        self._client = client
        self._receiver = receiver
        self._node_id = node_id
        self._mission_ref = mission_ref
        self._allowed_addresses = allowed_addresses
        self._timeout_seconds = timeout_seconds

    async def execute(
        self, operation: str, inputs: JsonObject
    ) -> tuple[CapabilityRunRef, CapabilityResult]:
        run_ref = CapabilityRunRef(f"run-listener-smoke-{uuid.uuid4()}")
        delivery = InvocationDelivery(
            invocation=CapabilityInvocation(
                run_id=run_ref,
                capability_id="network.listener",
                operation=operation,
                mission_ref=self._mission_ref,
                inputs=inputs,
            ),
            mission=MissionProjection(
                mission_ref=self._mission_ref,
                name="Manual incoming Session smoke test",
            ),
            allowed_addresses=self._allowed_addresses,
        )
        await self._client.submit_invocation(self._node_id, delivery)
        deadline = asyncio.get_running_loop().time() + self._timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            status = await self._transport.query_run_status(self._node_id, run_ref)
            if status is not None and status.is_terminal:
                break
            await asyncio.sleep(0.25)
        else:
            raise TimeoutError(f"listener Capability Run did not become terminal: {run_ref}")
        await self._drain_outbox()
        envelope = self._receiver.result_for_run(run_ref)
        if envelope is None:
            raise RuntimeError(f"no CapabilityResult reached Core for {run_ref}")
        return run_ref, envelope.result

    async def wait_for_session(self, open_run_ref: CapabilityRunRef) -> SessionRef:
        deadline = asyncio.get_running_loop().time() + self._timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            await self._drain_outbox()
            for envelope in self._receiver.events_for_run(open_run_ref):
                if envelope.event.type != "session.created":
                    continue
                value = envelope.event.payload.get("session_ref")
                if isinstance(value, str):
                    return SessionRef(value)
            await asyncio.sleep(0.25)
        raise TimeoutError("no session.created Event reached Core before the timeout")

    async def _drain_outbox(self) -> None:
        count = await self._client.flush_node(self._node_id)
        for _ in range(count):
            await self._client.receive_one()


async def _run(arguments: argparse.Namespace) -> None:
    token = os.environ.get(arguments.token_environment_variable)
    if not token:
        raise RuntimeError(
            f"bearer token environment variable is unset: {arguments.token_environment_variable}"
        )
    if arguments.timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    if arguments.port < 1 or arguments.port > 65535:
        raise ValueError("manual smoke port must be between 1 and 65535")

    arguments.core_runtime_directory.mkdir(parents=True, exist_ok=True)
    database = CoreDatabase(
        DatabaseConfig.sqlite(arguments.core_runtime_directory / "core.sqlite3")
    )
    upgrade_database(database)
    receiver = CoreTransportReceiver(database)
    verify_tls: bool | Path = arguments.ca_file if arguments.ca_file is not None else True
    transport = McpTransport(
        McpClientConfiguration(
            endpoint_url=arguments.endpoint,
            node_id=arguments.node_id,
            bearer_token=SecretStr(token),
            verify_tls=verify_tls,
            allow_insecure_remote_transport=arguments.allow_insecure_remote_transport,
        )
    )
    client = CoreTransportClient(transport, receiver)
    smoke = ListenerSmoke(
        transport=transport,
        client=client,
        receiver=receiver,
        node_id=arguments.node_id,
        mission_ref=MissionRef("mission-manual-listener-smoke"),
        allowed_addresses=(arguments.bind_address, arguments.allowed_peer_address),
        timeout_seconds=arguments.timeout_seconds,
    )
    resource_ref: ResourceRef | None = None
    session_ref: SessionRef | None = None
    try:
        await transport.connect()
        advertisement = await client.discover_node(arguments.node_id)
        if not any(
            str(definition.capability_id) == "network.listener"
            for definition in advertisement.capabilities
        ):
            raise RuntimeError("Node did not advertise network.listener")

        open_run, opened = await smoke.execute(
            "open",
            {
                "bind_address": arguments.bind_address,
                "port": arguments.port,
                "allowed_remote_addresses": [arguments.allowed_peer_address],
                "max_sessions": 2,
            },
        )
        if opened.outcome.code != "LISTENER_OPENED" or not opened.resources:
            raise RuntimeError(f"listener open failed: {opened.outcome.code}")
        resource_ref = opened.resources[0].resource_id
        bound_port = opened.resources[0].lifecycle_metadata.get("bound_port")
        if not isinstance(bound_port, int):
            raise RuntimeError("listener result omitted its bound port")

        print(
            f"Listener {resource_ref} is ready on {arguments.bind_address}:{bound_port}.\n"
            "Start listener_test_client.py from the explicitly authorized peer now."
        )
        session_ref = await smoke.wait_for_session(open_run)
        print(f"Core received session.created for {session_ref}.")

        _receive_run, received = await smoke.execute(
            "receive",
            {"session_ref": str(session_ref), "max_bytes": 4096, "timeout_seconds": 10},
        )
        encoded = received.outcome.details.get("payload_base64")
        if not isinstance(encoded, str) or base64.b64decode(encoded) != b"hello-boberagent":
            raise RuntimeError("listener did not receive the expected harmless fixture bytes")

        _send_run, sent = await smoke.execute(
            "send",
            {
                "session_ref": str(session_ref),
                "payload_base64": base64.b64encode(b"pong-boberagent").decode("ascii"),
                "timeout_seconds": 10,
            },
        )
        if sent.outcome.code != "STREAM_BYTES_SENT":
            raise RuntimeError(f"listener send failed: {sent.outcome.code}")

        _close_session_run, closed = await smoke.execute(
            "close_session", {"session_ref": str(session_ref)}
        )
        if closed.outcome.code not in {
            "STREAM_SESSION_CLOSED",
            "STREAM_SESSION_ALREADY_CLOSED",
        }:
            raise RuntimeError(f"Session close failed: {closed.outcome.code}")
        session_ref = None

        _close_listener_run, listener_closed = await smoke.execute(
            "close_listener", {"resource_ref": str(resource_ref)}
        )
        if listener_closed.outcome.code not in {"LISTENER_CLOSED", "LISTENER_ALREADY_CLOSED"}:
            raise RuntimeError(f"Listener close failed: {listener_closed.outcome.code}")
        resource_ref = None
        print("SUCCESS: harmless bytes crossed the incoming Session and both lifecycles closed.")
    finally:
        if session_ref is not None:
            await smoke.execute("close_session", {"session_ref": str(session_ref)})
        if resource_ref is not None:
            await smoke.execute("close_listener", {"resource_ref": str(resource_ref)})
        await transport.disconnect()
        database.dispose()


def main() -> None:
    asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    main()
