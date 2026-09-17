"""Narrow adapter from the neutral Node handshake to the Core registry."""

from boberagent_transport import CapabilityTransport, NodeAdvertisement

from .models import CapabilityProvider
from .registry import CapabilityRegistry


class CapabilityRegistrationClient:
    def __init__(self, transport: CapabilityTransport, registry: CapabilityRegistry) -> None:
        self._transport = transport
        self._registry = registry

    async def refresh_node(
        self, node_id: str
    ) -> tuple[NodeAdvertisement, tuple[CapabilityProvider, ...]]:
        advertisement = await self._transport.discover_node(node_id)
        providers = self._registry.register_or_refresh_node(advertisement)
        return advertisement, providers

    def mark_node_disconnected(self, node_id: str) -> None:
        self._registry.mark_node_stale(node_id)
