"""Small administrative entry point for the Execution Node MCP listener."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
from pathlib import Path

from boberagent_transport_mcp import McpServerConfiguration, McpTransportServer
from pydantic import SecretStr

from .config import NodeConfiguration, ToolConfiguration
from .node import ExecutionNode
from .transport import ExecutionNodeTransportEndpoint, NodeMcpArtifactSource


def _runtime_directory(value: str) -> Path:
    if not value.strip():
        raise argparse.ArgumentTypeError("--runtime-directory must not be empty")
    return Path(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a BoberAgent Execution Node MCP server")
    parser.add_argument("--runtime-directory", type=_runtime_directory, required=True)
    parser.add_argument("--bind-host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--capability-path", type=Path, action="append", default=[])
    parser.add_argument(
        "--tool",
        action="append",
        default=[],
        metavar="NAME=EXECUTABLE",
        help="register a logical tool executable",
    )
    parser.add_argument(
        "--tool-version-arg",
        action="append",
        default=[],
        metavar="NAME=ARG",
        help="configure one version-probe argument for a registered tool",
    )
    parser.add_argument("--tls-certificate", type=Path)
    parser.add_argument("--tls-private-key", type=Path)
    parser.add_argument("--allow-insecure-remote-transport", action="store_true")
    parser.add_argument(
        "--token-environment-variable",
        default="BOBERAGENT_MCP_TOKEN",
        help="environment variable containing the bearer token",
    )
    return parser


def _tools(
    values: list[str], version_args: list[str] | None = None
) -> dict[str, ToolConfiguration]:
    tools: dict[str, ToolConfiguration] = {}
    for value in values:
        name, separator, executable = value.partition("=")
        if not separator or not name or not executable:
            raise ValueError("--tool must use NAME=EXECUTABLE")
        if name in tools:
            raise ValueError(f"duplicate tool name: {name}")
        tools[name] = ToolConfiguration(executable=executable)
    configured: set[str] = set()
    for value in version_args or []:
        name, separator, argument = value.partition("=")
        if not separator or not name or not argument:
            raise ValueError("--tool-version-arg must use NAME=ARG")
        if name not in tools or name in configured:
            raise ValueError("version probe must name one registered tool exactly once")
        configured.add(name)
        tools[name] = tools[name].model_copy(update={"version_args": (argument,)})
    return tools


async def _run(arguments: argparse.Namespace) -> None:
    token = os.environ.get(arguments.token_environment_variable)
    if not token:
        raise RuntimeError(
            f"bearer token environment variable is unset: {arguments.token_environment_variable}"
        )
    node_configuration = NodeConfiguration.for_runtime_directory(
        arguments.runtime_directory,
        capability_paths=tuple(arguments.capability_path),
        tools=_tools(arguments.tool, arguments.tool_version_arg),
    )
    node = ExecutionNode(node_configuration)
    await node.initialize()
    if node.store is None:
        raise RuntimeError("Execution Node runtime store was not initialized")
    server = McpTransportServer(
        endpoint=ExecutionNodeTransportEndpoint(node),
        artifact_source=NodeMcpArtifactSource(
            store=node.store,
            spool_root=node_configuration.artifact_spool_root,
        ),
        configuration=McpServerConfiguration(
            bind_host=arguments.bind_host,
            port=arguments.port,
            bearer_token=SecretStr(token),
            tls_certificate=arguments.tls_certificate,
            tls_private_key=arguments.tls_private_key,
            allow_insecure_remote_transport=arguments.allow_insecure_remote_transport,
        ),
    )
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stopped.set)
    try:
        await server.start()
        print(f"BoberAgent MCP Node {server.node_id} listening at {server.endpoint_url}")
        await stopped.wait()
    finally:
        await server.stop()
        await node.shutdown()


def main() -> None:
    arguments = _parser().parse_args()
    asyncio.run(_run(arguments))


if __name__ == "__main__":
    main()
