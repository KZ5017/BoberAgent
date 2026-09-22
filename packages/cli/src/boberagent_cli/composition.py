"""Concrete MCP composition isolated from transport-neutral CLI command logic."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from boberagent_core import (
    CapabilityRegistry,
    CapabilityRouter,
    CoreDatabase,
    CoreInteractionService,
    CoreMcpNodeConnection,
    CoreTransportClient,
    CoreTransportReceiver,
    ResultIngestionService,
    WorkflowService,
)
from boberagent_transport_mcp import McpClientConfiguration
from pydantic import SecretStr

from .errors import CliInvalidInput


@dataclass(frozen=True, slots=True)
class RemoteNodeConfiguration:
    endpoint_url: str
    node_id: str
    bearer_token: SecretStr
    request_timeout_seconds: float = 30.0
    verify_tls: bool | Path = True
    allow_insecure_remote_transport: bool = False

    @classmethod
    def from_values(
        cls,
        *,
        endpoint_url: str | None,
        node_id: str | None,
        bearer_token_environment: str,
        environment: Mapping[str, str],
        request_timeout_seconds: float,
        verify_tls: bool,
        allow_insecure_remote_transport: bool,
    ) -> RemoteNodeConfiguration:
        if endpoint_url is None or node_id is None:
            raise CliInvalidInput("workflow dispatch requires --node-url and --node-id")
        token = environment.get(bearer_token_environment)
        if token is None or not token:
            raise CliInvalidInput(
                f"workflow dispatch requires bearer token environment variable "
                f"{bearer_token_environment}"
            )
        return cls(
            endpoint_url=endpoint_url,
            node_id=node_id,
            bearer_token=SecretStr(token),
            request_timeout_seconds=request_timeout_seconds,
            verify_tls=verify_tls,
            allow_insecure_remote_transport=allow_insecure_remote_transport,
        )


class WorkflowCommandSession(Protocol):
    workflows: WorkflowService

    async def receive_pending(self) -> int: ...


type WorkflowSessionFactory = Callable[
    [CoreDatabase, RemoteNodeConfiguration],
    AbstractAsyncContextManager[WorkflowCommandSession],
]


class McpWorkflowCommandSession:
    def __init__(
        self,
        database: CoreDatabase,
        configuration: RemoteNodeConfiguration,
    ) -> None:
        registry = CapabilityRegistry(database)
        client_configuration = McpClientConfiguration(
            endpoint_url=configuration.endpoint_url,
            node_id=configuration.node_id,
            bearer_token=configuration.bearer_token,
            request_timeout_seconds=configuration.request_timeout_seconds,
            verify_tls=configuration.verify_tls,
            allow_insecure_remote_transport=(configuration.allow_insecure_remote_transport),
        )
        self._node_id = configuration.node_id
        self._connection = CoreMcpNodeConnection(client_configuration, registry)
        router = CapabilityRouter(registry, self._connection.transport)
        ingestion = ResultIngestionService(database)
        receiver = CoreTransportReceiver(database, result_ingestion=ingestion)
        self._client = CoreTransportClient(self._connection.transport, receiver)
        self.workflows = WorkflowService(database, router)
        self.interactions = CoreInteractionService(database, self._connection.transport)

    async def connect(self) -> None:
        await self._connection.connect_and_refresh()

    async def disconnect(self) -> None:
        await self._connection.disconnect()

    async def receive_pending(self) -> int:
        count = await self._client.flush_node(self._node_id)
        for _ in range(count):
            await self._client.receive_one()
        return count


@asynccontextmanager
async def mcp_workflow_session(
    database: CoreDatabase,
    configuration: RemoteNodeConfiguration,
) -> AsyncIterator[WorkflowCommandSession]:
    session = McpWorkflowCommandSession(database, configuration)
    await session.connect()
    try:
        yield session
    finally:
        await session.disconnect()
