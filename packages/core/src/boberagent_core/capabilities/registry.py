"""Core-owned durable Capability provider registry."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from boberagent_contracts import CapabilityDefinition, CapabilityRunRef
from boberagent_transport import NodeAdvertisement

from boberagent_core.clock import utc_now
from boberagent_core.persistence.database import CoreDatabase

from .errors import ConflictingProviderRegistration
from .models import (
    CapabilityProvider,
    ProviderAvailability,
    ProviderReportedStatus,
    RoutingDecision,
    provider_id_for,
    with_effective_staleness,
)

_ROUTABLE_NODE_LIFECYCLES = frozenset({"READY", "DEGRADED"})


class CapabilityRegistry:
    """Materialize Node advertisements without owning transport connectivity."""

    def __init__(
        self,
        database: CoreDatabase,
        *,
        freshness_ttl: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] = utc_now,
        mark_persisted_stale: bool = True,
    ) -> None:
        if freshness_ttl.total_seconds() <= 0:
            raise ValueError("provider freshness TTL must be positive")
        self._database = database
        self._freshness_ttl = freshness_ttl
        self._clock = clock
        if mark_persisted_stale:
            with self._database.unit_of_work() as work:
                work.capability_providers.mark_all_stale(
                    "Core registry restart requires a fresh Node handshake"
                )

    def register_or_refresh_node(
        self, advertisement: NodeAdvertisement
    ) -> tuple[CapabilityProvider, ...]:
        now = self._now()
        definition_ids = [
            str(definition.capability_id) for definition in advertisement.capabilities
        ]
        status_ids = [str(status.capability_id) for status in advertisement.capability_statuses]
        if len(definition_ids) != len(set(definition_ids)):
            raise ConflictingProviderRegistration(
                "Node advertisement contains conflicting duplicate Capability definitions"
            )
        if len(status_ids) != len(set(status_ids)):
            raise ConflictingProviderRegistration(
                "Node advertisement contains conflicting duplicate provider statuses"
            )
        if status_ids and set(status_ids) != set(definition_ids):
            raise ConflictingProviderRegistration(
                "Node provider statuses do not correspond to advertised definitions"
            )
        status_by_capability = {
            status.capability_id: status for status in advertisement.capability_statuses
        }
        advertised_ids = frozenset(definition_ids)
        providers: list[CapabilityProvider] = []
        with self._database.unit_of_work() as work:
            for definition in advertisement.capabilities:
                status_advertisement = status_by_capability[definition.capability_id]
                reported = ProviderReportedStatus(status_advertisement.status.value)
                availability, reason = _registration_availability(
                    reported_status=reported,
                    reported_reason=status_advertisement.reason,
                    node_lifecycle=advertisement.lifecycle,
                    database_ready=advertisement.database_ready,
                )
                provider_id = provider_id_for(advertisement.node_id, str(definition.capability_id))
                existing = work.capability_providers.get(provider_id)
                provider = CapabilityProvider(
                    provider_id=provider_id,
                    node_id=advertisement.node_id,
                    definition=definition,
                    reported_status=reported,
                    availability=availability,
                    first_registered_at=(now if existing is None else existing.first_registered_at),
                    last_seen_at=now,
                    node_lifecycle=advertisement.lifecycle,
                    node_database_ready=advertisement.database_ready,
                    node_degraded_reasons=advertisement.degraded_reasons,
                    unavailability_reason=reason,
                )
                providers.append(work.capability_providers.upsert(provider))
            work.capability_providers.mark_missing_from_refresh(
                node_id=advertisement.node_id,
                advertised_capability_ids=advertised_ids,
                reason="capability was omitted from the latest Node advertisement",
            )
        return tuple(providers)

    def list_capabilities(self) -> tuple[CapabilityDefinition, ...]:
        with self._database.unit_of_work() as work:
            providers = work.capability_providers.list_all()
        definitions: dict[str, CapabilityDefinition] = {}
        for provider in providers:
            definitions.setdefault(str(provider.capability_id), provider.definition)
        return tuple(definitions[key] for key in sorted(definitions))

    def get_capability(self, capability_id: str) -> CapabilityDefinition | None:
        providers = self.list_providers(capability_id)
        return None if not providers else providers[0].definition

    def list_providers(self, capability_id: str) -> tuple[CapabilityProvider, ...]:
        with self._database.unit_of_work() as work:
            providers = work.capability_providers.list_for_capability(capability_id)
        return tuple(self._effective(provider) for provider in providers)

    def get_provider(self, provider_id: UUID) -> CapabilityProvider | None:
        with self._database.unit_of_work() as work:
            provider = work.capability_providers.get(provider_id)
        return None if provider is None else self._effective(provider)

    def mark_node_stale(
        self,
        node_id: str,
        *,
        reason: str = "Node transport registration is disconnected",
    ) -> None:
        with self._database.unit_of_work() as work:
            work.capability_providers.mark_node_stale(node_id, reason)

    def record_routing_decision(self, decision: RoutingDecision) -> RoutingDecision:
        with self._database.unit_of_work() as work:
            return work.routing_decisions.add(decision)

    def routing_decision_for_run(self, run_ref: CapabilityRunRef) -> RoutingDecision | None:
        with self._database.unit_of_work() as work:
            return work.routing_decisions.get(run_ref)

    def _effective(self, provider: CapabilityProvider) -> CapabilityProvider:
        return with_effective_staleness(
            provider,
            now=self._now(),
            stale_after_seconds=self._freshness_ttl.total_seconds(),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Capability Registry clock must return timezone-aware datetime")
        return value


def _registration_availability(
    *,
    reported_status: ProviderReportedStatus,
    reported_reason: str | None,
    node_lifecycle: str,
    database_ready: bool,
) -> tuple[ProviderAvailability, str | None]:
    if not database_ready:
        return ProviderAvailability.UNAVAILABLE, "Node runtime database is not ready"
    if node_lifecycle not in _ROUTABLE_NODE_LIFECYCLES:
        return (
            ProviderAvailability.UNAVAILABLE,
            f"Node lifecycle does not accept work: {node_lifecycle}",
        )
    if reported_status is not ProviderReportedStatus.AVAILABLE:
        return (
            ProviderAvailability.UNAVAILABLE,
            reported_reason or f"Node reported provider status {reported_status.value}",
        )
    return ProviderAvailability.AVAILABLE, None
