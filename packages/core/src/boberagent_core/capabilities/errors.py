"""Core routing failures; none represent Capability execution results."""


class CapabilityRegistryError(ValueError):
    """Provider metadata violated registry identity or integrity rules."""


class ConflictingProviderRegistration(CapabilityRegistryError):
    """Stable provider identity was reused for incompatible metadata."""


class CapabilityRoutingError(RuntimeError):
    """No Capability was executed because routing could not be completed."""


class UnknownCapability(CapabilityRoutingError):
    pass


class UnsupportedOperation(CapabilityRoutingError):
    pass


class NoEligibleProvider(CapabilityRoutingError):
    pass


class ExplicitProviderUnavailable(CapabilityRoutingError):
    pass


class ConflictingRoutingDecision(CapabilityRoutingError):
    pass
