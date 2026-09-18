"""Deterministic technical provider selection and existing-transport dispatch."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from boberagent_contracts import CapabilityInvocation, CapabilityRunRef
from boberagent_transport import (
    CapabilityTransport,
    InvocationDelivery,
    TransportMessageId,
)

from boberagent_core.clock import utc_now

from .errors import (
    ExplicitProviderUnavailable,
    NoEligibleProvider,
    UnknownCapability,
    UnsupportedOperation,
)
from .models import CapabilityProvider, ProviderAvailability, RoutingDecision
from .registry import CapabilityRegistry


class CapabilityRouter:
    """Select exactly once using persisted Core registry state; never execute code."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        transport: CapabilityTransport,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._registry = registry
        self._transport = transport
        self._clock = clock

    def select_provider(
        self,
        *,
        capability_id: str,
        operation: str,
        provider_id: UUID | None = None,
        node_id: str | None = None,
    ) -> CapabilityProvider:
        providers = self._registry.list_providers(capability_id)
        if not providers:
            raise UnknownCapability(f"Capability is not registered: {capability_id}")
        if not any(
            operation in {definition.name for definition in provider.definition.operations}
            for provider in providers
        ):
            raise UnsupportedOperation(
                f"No provider for {capability_id} declares operation {operation}"
            )

        constrained = providers
        if provider_id is not None:
            constrained = tuple(
                provider for provider in constrained if provider.provider_id == provider_id
            )
        if node_id is not None:
            constrained = tuple(provider for provider in constrained if provider.node_id == node_id)
        if (provider_id is not None or node_id is not None) and not constrained:
            raise ExplicitProviderUnavailable(
                "The explicitly requested provider or Node does not provide the Capability"
            )

        operation_capable = tuple(
            provider
            for provider in constrained
            if operation in {definition.name for definition in provider.definition.operations}
        )
        if (provider_id is not None or node_id is not None) and not operation_capable:
            raise ExplicitProviderUnavailable(
                "The explicitly requested provider does not support the requested operation"
            )
        eligible = tuple(
            provider
            for provider in operation_capable
            if provider.availability is ProviderAvailability.AVAILABLE
        )
        if not eligible:
            if provider_id is not None or node_id is not None:
                statuses = ", ".join(
                    f"{provider.provider_id}={provider.availability.value}"
                    for provider in operation_capable
                )
                raise ExplicitProviderUnavailable(
                    f"The explicitly requested provider is not available: {statuses}"
                )
            raise NoEligibleProvider(f"No eligible provider is available for {capability_id}")
        return min(eligible, key=lambda provider: str(provider.provider_id))

    def selected_provider_for_run(self, run_ref: CapabilityRunRef) -> CapabilityProvider | None:
        """Resolve an earlier durable routing decision for restart reconciliation."""

        decision = self._registry.routing_decision_for_run(run_ref)
        if decision is None:
            return None
        provider = self._registry.get_provider(decision.provider_id)
        if provider is None:
            raise ExplicitProviderUnavailable(
                "the provider recorded for this CapabilityRun no longer exists"
            )
        if provider.availability is not ProviderAvailability.AVAILABLE:
            raise ExplicitProviderUnavailable(
                "the provider recorded for this CapabilityRun is not currently available"
            )
        if provider.node_id != decision.node_id:
            raise ExplicitProviderUnavailable(
                "the provider recorded for this CapabilityRun changed Node identity"
            )
        return provider

    async def dispatch(
        self,
        *,
        invocation: CapabilityInvocation,
        delivery: InvocationDelivery,
        provider: CapabilityProvider,
    ) -> TransportMessageId:
        if delivery.invocation != invocation:
            raise ValueError("InvocationDelivery does not contain the routed CapabilityInvocation")
        if invocation.capability_id != provider.capability_id or invocation.operation not in {
            definition.name for definition in provider.definition.operations
        }:
            raise ExplicitProviderUnavailable(
                "selected provider is incompatible with the CapabilityInvocation"
            )
        current = self._registry.get_provider(provider.provider_id)
        if current is None or current.availability is not ProviderAvailability.AVAILABLE:
            raise ExplicitProviderUnavailable("selected provider is no longer eligible")
        if current.capability_id != invocation.capability_id or invocation.operation not in {
            definition.name for definition in current.definition.operations
        }:
            raise ExplicitProviderUnavailable(
                "selected provider metadata changed before dispatch and is now incompatible"
            )
        selected_at = self._clock()
        if selected_at.tzinfo is None or selected_at.utcoffset() is None:
            raise ValueError("Capability Router clock must return timezone-aware datetime")
        self._registry.record_routing_decision(
            RoutingDecision(
                run_ref=invocation.run_id,
                capability_id=invocation.capability_id,
                operation=invocation.operation,
                provider_id=current.provider_id,
                node_id=current.node_id,
                implementation_version=current.implementation_version,
                selected_at=selected_at,
            )
        )
        return await self._transport.submit_invocation(current.node_id, delivery)
