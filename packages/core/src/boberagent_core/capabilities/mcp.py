"""Core composition helper for one explicitly configured MCP Node connection."""

from __future__ import annotations

from boberagent_transport import NodeAdvertisement
from boberagent_transport_mcp import McpClientConfiguration, McpTransport

from .models import CapabilityProvider
from .registry import CapabilityRegistry
from .transport import CapabilityRegistrationClient


class CoreMcpNodeConnection:
    """Wire the concrete carrier to the transport-neutral Core registry boundary."""

    def __init__(
        self,
        configuration: McpClientConfiguration,
        registry: CapabilityRegistry,
    ) -> None:
        self.transport = McpTransport(configuration)
        self._registration = CapabilityRegistrationClient(self.transport, registry)
        self._node_id = configuration.node_id

    async def connect_and_refresh(
        self,
    ) -> tuple[NodeAdvertisement, tuple[CapabilityProvider, ...]]:
        await self.transport.connect()
        try:
            return await self._registration.refresh_node(self._node_id)
        except BaseException:
            await self.transport.disconnect()
            raise

    async def disconnect(self) -> None:
        await self.transport.disconnect()
        self._registration.mark_node_disconnected(self._node_id)
