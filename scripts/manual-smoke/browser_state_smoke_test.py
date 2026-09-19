"""Manual WSL Core to Kali Node browser Session state smoke test."""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from pathlib import Path

from boberagent_contracts import (
    AssetRef,
    CapabilityInvocation,
    CapabilityResult,
    CapabilityRunRef,
    JsonObject,
    MissionRef,
    SessionRef,
)
from boberagent_core import CoreDatabase, CoreTransportClient, CoreTransportReceiver, DatabaseConfig
from boberagent_core.persistence.migrations import upgrade_database
from boberagent_sdk import parse_browser_url
from boberagent_transport import AssetProjection, InvocationDelivery, MissionProjection
from boberagent_transport_mcp import McpClientConfiguration, McpTransport
from pydantic import SecretStr


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prove stateful browser.interaction across real MCP Capability Runs"
    )
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--core-runtime-directory", type=Path, required=True)
    parser.add_argument("--asset-ref", required=True)
    parser.add_argument("--set-url", required=True)
    parser.add_argument("--check-url", required=True)
    parser.add_argument("--expected-title", default="cookie-preserved")
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--allow-insecure-remote-transport", action="store_true")
    parser.add_argument("--token-environment-variable", default="BOBERAGENT_MCP_TOKEN")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    return parser


class BrowserSmoke:
    def __init__(
        self,
        *,
        transport: McpTransport,
        client: CoreTransportClient,
        receiver: CoreTransportReceiver,
        node_id: str,
        mission_ref: MissionRef,
        asset_ref: AssetRef,
        allowed_host: str,
        timeout_seconds: float,
    ) -> None:
        self._transport = transport
        self._client = client
        self._receiver = receiver
        self._node_id = node_id
        self._mission_ref = mission_ref
        self._asset_ref = asset_ref
        self._allowed_host = allowed_host
        self._timeout_seconds = timeout_seconds

    async def execute(self, operation: str, inputs: JsonObject) -> CapabilityResult:
        run_ref = CapabilityRunRef(f"run-browser-smoke-{uuid.uuid4()}")
        delivery = InvocationDelivery(
            invocation=CapabilityInvocation(
                run_id=run_ref,
                capability_id="browser.interaction",
                operation=operation,
                mission_ref=self._mission_ref,
                inputs=inputs,
            ),
            mission=MissionProjection(
                mission_ref=self._mission_ref,
                name="Manual stateful browser smoke test",
            ),
            allowed_assets=(self._asset_ref,),
            allowed_addresses=(self._allowed_host,),
            assets=(
                AssetProjection(
                    asset_ref=self._asset_ref,
                    primary_address=self._allowed_host,
                ),
            ),
        )
        await self._client.submit_invocation(self._node_id, delivery)
        deadline = asyncio.get_running_loop().time() + self._timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            status = await self._transport.query_run_status(self._node_id, run_ref)
            if status is not None and status.is_terminal:
                break
            await asyncio.sleep(0.25)
        else:
            raise TimeoutError(f"browser Capability Run did not become terminal: {run_ref}")

        count = await self._client.flush_node(self._node_id)
        for _ in range(count):
            await self._client.receive_one()
        envelope = self._receiver.result_for_run(run_ref)
        if envelope is None:
            raise RuntimeError(f"no CapabilityResult reached Core for {run_ref}")
        return envelope.result


async def _run(arguments: argparse.Namespace) -> None:
    token = os.environ.get(arguments.token_environment_variable)
    if not token:
        raise RuntimeError(
            f"bearer token environment variable is unset: {arguments.token_environment_variable}"
        )
    set_target = parse_browser_url(arguments.set_url)
    check_target = parse_browser_url(arguments.check_url)
    if set_target.host != check_target.host:
        raise ValueError("set and check URLs must use the same normalized authorized host")
    if arguments.timeout_seconds <= 0:
        raise ValueError("timeout must be positive")

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
    smoke = BrowserSmoke(
        transport=transport,
        client=client,
        receiver=receiver,
        node_id=arguments.node_id,
        mission_ref=MissionRef("mission-manual-browser-smoke"),
        asset_ref=AssetRef(arguments.asset_ref),
        allowed_host=set_target.host,
        timeout_seconds=arguments.timeout_seconds,
    )
    try:
        await transport.connect()
        advertisement = await client.discover_node(arguments.node_id)
        browser_definition = next(
            (
                definition
                for definition in advertisement.capabilities
                if str(definition.capability_id) == "browser.interaction"
            ),
            None,
        )
        if browser_definition is None:
            raise RuntimeError("Node did not advertise browser.interaction")

        print(f"Connected to {advertisement.node_id}; opening browser Session...")
        opened = await smoke.execute("open", {"asset_ref": arguments.asset_ref})
        if not opened.execution_status.is_terminal or not opened.sessions:
            raise RuntimeError(f"browser open failed: {opened.outcome.code}")
        session_ref = SessionRef(opened.sessions[0].session_id)

        set_result = await smoke.execute(
            "navigate",
            {
                "asset_ref": arguments.asset_ref,
                "session_ref": str(session_ref),
                "url": arguments.set_url,
            },
        )
        if set_result.outcome.code != "BROWSER_NAVIGATED":
            raise RuntimeError(f"cookie-setting navigation failed: {set_result.outcome.code}")

        check_result = await smoke.execute(
            "navigate",
            {
                "asset_ref": arguments.asset_ref,
                "session_ref": str(session_ref),
                "url": arguments.check_url,
            },
        )
        title = check_result.outcome.details.get("title")
        if title != arguments.expected_title:
            raise RuntimeError(
                f"browser Session state was not preserved: expected title "
                f"{arguments.expected_title!r}, got {title!r}"
            )

        closed = await smoke.execute(
            "close",
            {"asset_ref": arguments.asset_ref, "session_ref": str(session_ref)},
        )
        if closed.outcome.code not in {"BROWSER_SESSION_CLOSED", "BROWSER_SESSION_ALREADY_CLOSED"}:
            raise RuntimeError(f"browser close failed: {closed.outcome.code}")

        unavailable = await smoke.execute(
            "navigate",
            {
                "asset_ref": arguments.asset_ref,
                "session_ref": str(session_ref),
                "url": arguments.check_url,
            },
        )
        if unavailable.outcome.code != "SESSION_UNAVAILABLE":
            raise RuntimeError("closed browser Session unexpectedly remained usable")
        print(f"SUCCESS: {session_ref} preserved browser state and closed cleanly.")
    finally:
        await transport.disconnect()
        database.dispose()


def main() -> None:
    asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    main()
