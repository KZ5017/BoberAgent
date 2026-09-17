"""Core Capability Registry and deterministic Router public surface."""

from .errors import (
    CapabilityRegistryError,
    CapabilityRoutingError,
    ConflictingProviderRegistration,
    ConflictingRoutingDecision,
    ExplicitProviderUnavailable,
    NoEligibleProvider,
    UnknownCapability,
    UnsupportedOperation,
)
from .models import (
    CapabilityProvider,
    ProviderAvailability,
    ProviderId,
    ProviderReportedStatus,
    RoutingDecision,
    provider_id_for,
)
from .registry import CapabilityRegistry
from .router import CapabilityRouter
from .transport import CapabilityRegistrationClient

__all__ = [
    "CapabilityProvider",
    "CapabilityRegistrationClient",
    "CapabilityRegistry",
    "CapabilityRegistryError",
    "CapabilityRouter",
    "CapabilityRoutingError",
    "ConflictingProviderRegistration",
    "ConflictingRoutingDecision",
    "ExplicitProviderUnavailable",
    "NoEligibleProvider",
    "ProviderAvailability",
    "ProviderId",
    "ProviderReportedStatus",
    "RoutingDecision",
    "UnknownCapability",
    "UnsupportedOperation",
    "provider_id_for",
]
