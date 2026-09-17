"""Core-owned provider registry and routing provenance models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid5

from boberagent_contracts import (
    CapabilityDefinition,
    CapabilityId,
    CapabilityRunRef,
    OperationName,
)
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

ProviderId = UUID

_PROVIDER_NAMESPACE = UUID("aa3e648b-55b6-572c-98b8-31ad7d8e0a25")


class ProviderReportedStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class ProviderAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


class CapabilityProvider(BaseModel):
    """One concrete Node implementation of a stable Capability identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    provider_id: ProviderId
    node_id: str = Field(min_length=3, max_length=255)
    definition: CapabilityDefinition
    reported_status: ProviderReportedStatus
    availability: ProviderAvailability
    first_registered_at: AwareDatetime
    last_seen_at: AwareDatetime
    node_lifecycle: str = Field(min_length=1, max_length=32)
    node_database_ready: bool
    node_degraded_reasons: tuple[str, ...] = ()
    unavailability_reason: str | None = Field(default=None, min_length=1, max_length=2048)

    @property
    def capability_id(self) -> CapabilityId:
        return self.definition.capability_id

    @property
    def implementation_version(self) -> str:
        return self.definition.implementation_version


class RoutingDecision(BaseModel):
    """Immutable technical selection provenance for one CapabilityRun."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    run_ref: CapabilityRunRef
    capability_id: CapabilityId
    operation: OperationName
    provider_id: ProviderId
    node_id: str = Field(min_length=3, max_length=255)
    implementation_version: str = Field(min_length=3, max_length=64)
    selected_at: AwareDatetime


def provider_id_for(node_id: str, capability_id: str) -> ProviderId:
    """Derive stable identity from Node and Capability, independent of implementation version."""

    return uuid5(_PROVIDER_NAMESPACE, f"{node_id}\0{capability_id}")


def with_effective_staleness(
    provider: CapabilityProvider,
    *,
    now: datetime,
    stale_after_seconds: float,
) -> CapabilityProvider:
    if (
        provider.availability is ProviderAvailability.AVAILABLE
        and (now - provider.last_seen_at).total_seconds() > stale_after_seconds
    ):
        return provider.model_copy(
            update={
                "availability": ProviderAvailability.STALE,
                "unavailability_reason": "provider registration exceeded the freshness TTL",
            }
        )
    return provider
