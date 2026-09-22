"""Execution Node MCP Streamable HTTP server adapter."""

from __future__ import annotations

import asyncio
import contextlib
import socket
from typing import cast

import uvicorn
from boberagent_contracts import ArtifactRef
from boberagent_transport import (
    TransportFailure,
    TransportInteractionEndpoint,
    TransportNodeEndpoint,
    parse_invocation,
)
from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from .auth import StaticBearerTokenVerifier
from .config import McpServerConfiguration
from .models import ArtifactReadRequest, ArtifactReadResponse
from .source import McpArtifactSource


class McpTransportServer:
    """Expose only the bounded BoberAgent protocol over MCP tools."""

    def __init__(
        self,
        *,
        endpoint: TransportNodeEndpoint,
        configuration: McpServerConfiguration,
        artifact_source: McpArtifactSource | None = None,
    ) -> None:
        self._endpoint = endpoint
        self.configuration = configuration
        self._artifact_source = artifact_source
        self._failures: asyncio.Queue[TransportFailure] = asyncio.Queue(
            configuration.outbound_batch_size
        )
        self._tasks: set[asyncio.Task[None]] = set()
        self._uvicorn: uvicorn.Server | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._socket: socket.socket | None = None
        self._bound_port: int | None = None

        base_url = f"{configuration.scheme}://{configuration.bind_host}:{configuration.port}"
        self._mcp = MCPServer(
            name="BoberAgent Execution Node",
            version="1.0",
            token_verifier=StaticBearerTokenVerifier(configuration.bearer_token.get_secret_value()),
            auth=AuthSettings(
                issuer_url=AnyHttpUrl("https://boberagent.invalid"),
                resource_server_url=AnyHttpUrl(base_url),
                required_scopes=["boberagent.transport"],
                validate_token_resource=False,
            ),
        )
        self._register_tools()

    @property
    def node_id(self) -> str:
        return self._endpoint.node_id

    @property
    def endpoint_url(self) -> str:
        if self._bound_port is None:
            raise RuntimeError("MCP server is not running")
        host = self.configuration.bind_host
        display_host = "127.0.0.1" if host == "0.0.0.0" else host
        return f"{self.configuration.scheme}://{display_host}:{self._bound_port}/mcp"

    async def start(self) -> None:
        if self._serve_task is not None:
            return
        listening_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listening_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listening_socket.bind((self.configuration.bind_host, self.configuration.port))
        listening_socket.listen(2048)
        listening_socket.setblocking(False)
        self._socket = listening_socket
        self._bound_port = int(listening_socket.getsockname()[1])

        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                f"{self.configuration.bind_host}:*",
                "127.0.0.1:*",
                "localhost:*",
                "[::1]:*",
            ],
            allowed_origins=[
                f"{self.configuration.scheme}://{self.configuration.bind_host}:*",
                f"{self.configuration.scheme}://127.0.0.1:*",
                f"{self.configuration.scheme}://localhost:*",
            ],
        )
        app = self._mcp.streamable_http_app(
            streamable_http_path="/mcp",
            json_response=True,
            stateless_http=True,
            max_request_body_size=self.configuration.max_request_body_bytes,
            transport_security=security,
            host=self.configuration.bind_host,
        )
        uvicorn_configuration = uvicorn.Config(
            app,
            host=self.configuration.bind_host,
            port=self._bound_port,
            log_level="warning",
            access_log=False,
            ssl_certfile=self.configuration.tls_certificate,
            ssl_keyfile=self.configuration.tls_private_key,
        )
        self._uvicorn = uvicorn.Server(uvicorn_configuration)
        self._serve_task = asyncio.create_task(
            self._uvicorn.serve(sockets=[listening_socket]),
            name=f"mcp-node-server:{self.node_id}",
        )
        for _ in range(100):
            if self._uvicorn.started:
                return
            if self._serve_task.done():
                await self._serve_task
                raise RuntimeError("MCP server exited during startup")
            await asyncio.sleep(0.01)
        await self.stop()
        raise TimeoutError("MCP server did not start")

    async def stop(self) -> None:
        server = self._uvicorn
        task = self._serve_task
        if server is not None:
            server.should_exit = True
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for execution in tuple(self._tasks):
            if not execution.done():
                execution.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        if self._socket is not None:
            self._socket.close()
        self._uvicorn = None
        self._serve_task = None
        self._socket = None
        self._bound_port = None

    def _register_tools(self) -> None:
        @self._mcp.tool(name="boberagent.handshake")
        async def handshake(payload: str) -> str:
            return (await self._endpoint.handshake(payload.encode("utf-8"))).decode("utf-8")

        @self._mcp.tool(name="boberagent.submit_invocation")
        async def submit_invocation(payload: str) -> str:
            envelope = parse_invocation(payload.encode("utf-8"))
            if envelope.node_id != self.node_id:
                raise ValueError("invocation targets a different Execution Node")
            task = asyncio.create_task(
                self._execute_invocation(payload.encode("utf-8")),
                name=f"mcp-invocation:{envelope.correlation_id}",
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return str(envelope.message_id)

        @self._mcp.tool(name="boberagent.poll_outbound")
        async def poll_outbound(limit: int = 100) -> list[str]:
            bounded = max(1, min(limit, self.configuration.outbound_batch_size))
            return [
                message.decode("utf-8")
                for message in (await self._endpoint.pending_outbound())[:bounded]
            ]

        @self._mcp.tool(name="boberagent.query_run_status")
        async def query_run_status(payload: str) -> str:
            return (await self._endpoint.query_run_status(payload.encode("utf-8"))).decode("utf-8")

        @self._mcp.tool(name="boberagent.interaction.respond")
        async def respond_to_interaction(payload: str) -> str:
            endpoint = cast(TransportInteractionEndpoint, self._endpoint)
            return (await endpoint.accept_interaction_response(payload.encode("utf-8"))).decode(
                "utf-8"
            )

        @self._mcp.tool(name="boberagent.acknowledge")
        async def acknowledge(payload: str) -> bool:
            await self._endpoint.acknowledge(payload.encode("utf-8"))
            return True

        @self._mcp.tool(name="boberagent.poll_failures")
        async def poll_failures(limit: int = 100) -> list[str]:
            bounded = max(1, min(limit, self.configuration.outbound_batch_size))
            failures: list[str] = []
            for _ in range(bounded):
                try:
                    failure = self._failures.get_nowait()
                except asyncio.QueueEmpty:
                    break
                failures.append(failure.model_dump_json())
                self._failures.task_done()
            return failures

        @self._mcp.tool(name="boberagent.list_artifacts")
        async def list_artifacts(limit: int = 100) -> list[str]:
            source = self._require_artifact_source()
            bounded = max(1, min(limit, self.configuration.outbound_batch_size))
            return [item.model_dump_json() for item in await source.pending_artifacts(bounded)]

        @self._mcp.tool(name="boberagent.read_artifact")
        async def read_artifact(payload: str) -> str:
            request = ArtifactReadRequest.model_validate_json(payload)
            source = self._require_artifact_source()
            data = await source.read_artifact_chunk(
                request.artifact_ref,
                offset=request.offset,
                max_bytes=request.max_bytes,
            )
            response = ArtifactReadResponse(
                artifact_ref=request.artifact_ref,
                offset=request.offset,
                data=data,
                end_of_artifact=len(data) < request.max_bytes,
            )
            return response.model_dump_json()

        @self._mcp.tool(name="boberagent.complete_artifact")
        async def complete_artifact(artifact_ref: str) -> bool:
            await self._require_artifact_source().mark_artifact_synchronized(
                ArtifactRef(artifact_ref)
            )
            return True

        @self._mcp.tool(name="boberagent.fail_artifact")
        async def fail_artifact(artifact_ref: str, error: str) -> bool:
            await self._require_artifact_source().mark_artifact_failed(
                ArtifactRef(artifact_ref), error[:1024]
            )
            return True

    async def _execute_invocation(self, payload: bytes) -> None:
        envelope = parse_invocation(payload)
        try:
            await self._endpoint.accept_invocation(payload)
        except Exception as error:
            failure = TransportFailure(
                code=getattr(error, "code", "ENDPOINT_FAILURE"),
                message=f"Node endpoint rejected invocation: {type(error).__name__}",
                node_id=self.node_id,
                message_id=str(envelope.message_id),
                correlation_id=envelope.correlation_id,
            )
            self._put_failure(failure)

    def _put_failure(self, failure: TransportFailure) -> None:
        if self._failures.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._failures.get_nowait()
                self._failures.task_done()
        self._failures.put_nowait(failure)

    def _require_artifact_source(self) -> McpArtifactSource:
        if self._artifact_source is None:
            raise RuntimeError("Artifact synchronization is unavailable")
        return self._artifact_source
