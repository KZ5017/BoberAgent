"""Controlled errors a capability may receive from or raise through the SDK."""


class CapabilityError(Exception):
    """Base class for expected capability/runtime interaction failures."""


class InputError(CapabilityError):
    """Validated input is semantically unsuitable for the requested operation."""


class DependencyError(CapabilityError):
    """A declared capability dependency is missing or unusable."""


class ScopeViolation(CapabilityError):
    """A requested target is outside the invocation's authorized scope."""


class PolicyDenied(CapabilityError):
    """Platform policy denied an otherwise valid service request."""


class ResourceUnavailable(CapabilityError):
    """A required Resource does not exist or cannot currently be leased."""


class SessionUnavailable(CapabilityError):
    """A required Session does not exist or cannot currently be leased."""


class InteractionUnavailable(CapabilityError):
    """No response can be supplied for an InteractionRequest."""


class ExecutionTimeout(CapabilityError):
    """Managed execution exceeded its allowed duration."""


class ExecutionCancelled(CapabilityError):
    """Cooperative cancellation was requested for the current Run."""


class ToolExecutionError(CapabilityError):
    """Managed tool execution could not be performed as requested."""


class ResultValidationError(CapabilityError):
    """A capability produced an invalid Contract result."""
