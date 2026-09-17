"""Core Capability provider registry persistence and refresh semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from boberagent_contracts import (
    CONTRACT_VERSION,
    CapabilityDefinition,
    ExecutionCharacteristics,
    ExecutionDuration,
    ExecutionInteraction,
    InteractionSurfaceDeclaration,
    OperationDefinition,
    ResultObjectType,
    RetrySemantics,
    SchemaDeclaration,
    SideEffectCategory,
    SideEffectDeclaration,
    SideEffectLevel,
)
from boberagent_core import (
    CapabilityRegistry,
    ConflictingProviderRegistration,
    CoreDatabase,
    ProviderAvailability,
    ProviderReportedStatus,
    provider_id_for,
)
from boberagent_transport import (
    AdvertisedCapabilityStatus,
    CapabilityStatusAdvertisement,
    NodeAdvertisement,
    TransportMessageId,
)
from pydantic import ValidationError


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


def capability_definition(
    *, implementation_version: str = "0.1.0", operations: tuple[str, ...] = ("discover",)
) -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id="test.registry_capability",
        contract_version=CONTRACT_VERSION,
        implementation_version=implementation_version,
        title="Registry test Capability",
        description="Exercise provider registry behavior.",
        operations=tuple(
            OperationDefinition(
                name=operation,
                title=f"Operation {operation}",
                description="Perform a deterministic test operation.",
                input_schema=SchemaDeclaration(inline={"type": "object"}),
                result_types=(ResultObjectType.OBSERVATION,),
                retry_semantics=RetrySemantics.SAFE,
            )
            for operation in operations
        ),
        execution=ExecutionCharacteristics(
            duration=ExecutionDuration.ONE_SHOT,
            interaction=ExecutionInteraction.STATELESS,
        ),
        interaction_surfaces=InteractionSurfaceDeclaration(
            local_compute=True,
            target_network=False,
            internet_access=False,
            active_session=False,
            managed_resource=False,
        ),
        side_effects=(
            SideEffectDeclaration(
                category=SideEffectCategory.LOCAL_FILESYSTEM,
                level=SideEffectLevel.NONE,
            ),
        ),
        dependencies=(),
    )


def advertisement(
    node_id: str,
    *,
    definitions: tuple[CapabilityDefinition, ...] | None = None,
    status: AdvertisedCapabilityStatus = AdvertisedCapabilityStatus.AVAILABLE,
    lifecycle: str = "READY",
    database_ready: bool = True,
    timestamp: datetime = datetime(2026, 1, 1, tzinfo=UTC),
) -> NodeAdvertisement:
    selected = (capability_definition(),) if definitions is None else definitions
    return NodeAdvertisement(
        request_message_id=TransportMessageId(f"transport-handshake:{node_id}"),
        node_id=node_id,
        timestamp=timestamp,
        lifecycle=lifecycle,
        database_ready=database_ready,
        capabilities=selected,
        capability_statuses=tuple(
            CapabilityStatusAdvertisement(
                capability_id=definition.capability_id,
                status=status,
                reason=(None if status is AdvertisedCapabilityStatus.AVAILABLE else "test reason"),
            )
            for definition in selected
        ),
    )


def test_register_query_refresh_remove_and_version_update(database: CoreDatabase) -> None:
    clock = MutableClock(datetime(2026, 1, 1, tzinfo=UTC))
    registry = CapabilityRegistry(database, clock=clock)
    initial = registry.register_or_refresh_node(advertisement("node-registry-a"))[0]

    assert initial.provider_id == provider_id_for("node-registry-a", "test.registry_capability")
    assert registry.list_capabilities() == (initial.definition,)
    assert registry.get_capability("test.registry_capability") == initial.definition
    assert registry.list_providers("test.registry_capability") == (initial,)

    clock.advance(timedelta(seconds=30))
    refreshed = registry.register_or_refresh_node(advertisement("node-registry-a"))[0]
    assert refreshed.provider_id == initial.provider_id
    assert refreshed.first_registered_at == initial.first_registered_at
    assert refreshed.last_seen_at == clock.current
    assert len(registry.list_providers("test.registry_capability")) == 1

    clock.advance(timedelta(seconds=30))
    updated_definition = capability_definition(implementation_version="0.2.0")
    updated = registry.register_or_refresh_node(
        advertisement("node-registry-a", definitions=(updated_definition,))
    )[0]
    assert updated.provider_id == initial.provider_id
    assert updated.implementation_version == "0.2.0"

    registry.register_or_refresh_node(advertisement("node-registry-a", definitions=()))
    removed = registry.list_providers("test.registry_capability")[0]
    assert removed.availability is ProviderAvailability.UNAVAILABLE
    assert "omitted" in (removed.unavailability_reason or "")


def test_freshness_health_and_reported_status_control_availability(
    database: CoreDatabase,
) -> None:
    clock = MutableClock(datetime(2026, 1, 1, tzinfo=UTC))
    registry = CapabilityRegistry(database, clock=clock, freshness_ttl=timedelta(minutes=1))

    degraded_node = registry.register_or_refresh_node(
        advertisement("node-degraded", lifecycle="DEGRADED")
    )[0]
    assert degraded_node.availability is ProviderAvailability.AVAILABLE

    unavailable_provider = registry.register_or_refresh_node(
        advertisement(
            "node-provider-degraded",
            lifecycle="DEGRADED",
            status=AdvertisedCapabilityStatus.DEGRADED,
        )
    )[0]
    assert unavailable_provider.reported_status is ProviderReportedStatus.DEGRADED
    assert unavailable_provider.availability is ProviderAvailability.UNAVAILABLE

    offline = registry.register_or_refresh_node(advertisement("node-offline", lifecycle="OFFLINE"))[
        0
    ]
    assert offline.availability is ProviderAvailability.UNAVAILABLE

    clock.advance(timedelta(minutes=2))
    stale = registry.get_provider(degraded_node.provider_id)
    assert stale is not None
    assert stale.availability is ProviderAvailability.STALE


def test_restart_marks_persisted_provider_stale_until_refresh(database: CoreDatabase) -> None:
    clock = MutableClock(datetime(2026, 1, 1, tzinfo=UTC))
    first = CapabilityRegistry(database, clock=clock)
    provider = first.register_or_refresh_node(advertisement("node-restart"))[0]
    assert provider.availability is ProviderAvailability.AVAILABLE

    restarted = CapabilityRegistry(database, clock=clock)
    persisted = restarted.get_provider(provider.provider_id)
    assert persisted is not None
    assert persisted.availability is ProviderAvailability.STALE

    refreshed = restarted.register_or_refresh_node(advertisement("node-restart"))[0]
    assert refreshed.provider_id == provider.provider_id
    assert refreshed.availability is ProviderAvailability.AVAILABLE


def test_duplicate_capability_metadata_is_rejected_at_validated_boundary() -> None:
    definition = capability_definition()
    with pytest.raises(ValidationError, match="duplicate capability definitions"):
        advertisement("node-conflict", definitions=(definition, definition))


def test_registry_rejects_conflict_even_if_validation_boundary_is_bypassed(
    database: CoreDatabase,
) -> None:
    definition = capability_definition()
    malformed = NodeAdvertisement.model_construct(
        request_message_id=TransportMessageId("transport-handshake:malformed"),
        node_id="node-malformed",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        lifecycle="READY",
        database_ready=True,
        capabilities=(definition, definition),
        capability_statuses=(),
        degraded_reasons=(),
    )

    registry = CapabilityRegistry(database)
    with pytest.raises(ConflictingProviderRegistration, match="duplicate"):
        registry.register_or_refresh_node(malformed)
