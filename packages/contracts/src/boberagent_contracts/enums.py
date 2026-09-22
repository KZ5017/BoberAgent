"""Closed shared vocabularies defined by Capability Contract v1."""

from enum import StrEnum


class CapabilityRunStatus(StrEnum):
    """Lifecycle state for a CapabilityRun."""

    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_INPUT = "WAITING_INPUT"
    WAITING_RESOURCE = "WAITING_RESOURCE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"

    @property
    def is_terminal(self) -> bool:
        """Return whether no transition back to non-terminal state is permitted."""

        return self in {
            CapabilityRunStatus.COMPLETED,
            CapabilityRunStatus.FAILED,
            CapabilityRunStatus.CANCELLED,
            CapabilityRunStatus.TIMED_OUT,
        }


class CapabilityOutcomeCategory(StrEnum):
    """Shared high-level assessment outcome categories."""

    SUCCESS = "SUCCESS"
    NEGATIVE = "NEGATIVE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class DiagnosticSeverity(StrEnum):
    """Severity of execution-related diagnostic information."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class RetrySemantics(StrEnum):
    """Safety classification for retrying an operation."""

    SAFE = "SAFE"
    CONDITIONAL = "CONDITIONAL"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"


class AccessMode(StrEnum):
    """Contract-level Resource and Session access modes."""

    SHARED = "SHARED"
    EXCLUSIVE = "EXCLUSIVE"


class InteractionType(StrEnum):
    """Supported human/external interaction request classes."""

    CONFIRMATION = "confirmation"
    SINGLE_CHOICE = "single_choice"
    TEXT = "text"
    CHOICE = "choice"
    TEXT_INPUT = "text_input"
    STRUCTURED_FORM = "structured_form"
    SECRET_INPUT = "secret_input"
    ARTIFACT_INPUT = "artifact_input"


class InteractionLifecycle(StrEnum):
    """Durable lifecycle of one human interaction exchange."""

    REQUESTED = "REQUESTED"
    ANSWERED = "ANSWERED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ExecutionPlanStatus(StrEnum):
    """Lifecycle of structured execution intent."""

    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"


class ExecutionDuration(StrEnum):
    """Shared duration behavior advertised by a capability."""

    ONE_SHOT = "one_shot"
    LONG_RUNNING = "long_running"


class ExecutionInteraction(StrEnum):
    """Whether execution depends on persistent stateful context."""

    STATELESS = "stateless"
    STATEFUL = "stateful"


class DependencyType(StrEnum):
    """Kinds of capability implementation dependencies."""

    CAPABILITY = "capability"
    TOOL = "tool"
    RUNTIME = "runtime"
    RESOURCE = "resource"


class SideEffectCategory(StrEnum):
    """Shared categories for pre-execution side-effect declarations."""

    LOCAL_FILESYSTEM = "local_filesystem"
    LOCAL_PACKAGE_INSTALLATION = "local_package_installation"
    EXTERNAL_NETWORK = "external_network"
    TARGET_STATE = "target_state"
    CREDENTIAL_USE = "credential_use"
    LOCAL_CODE_EXECUTION = "local_code_execution"
    REMOTE_CODE_EXECUTION = "remote_code_execution"


class SideEffectLevel(StrEnum):
    """Declared degree or certainty of a possible side effect."""

    NONE = "none"
    READ = "read"
    WRITE = "write"
    MODIFY = "modify"
    POSSIBLE = "possible"
    EXPECTED = "expected"
    UNKNOWN = "unknown"


class ResultObjectType(StrEnum):
    """Object classes an operation may declare as outputs."""

    OBSERVATION = "observation"
    FINDING = "finding"
    ARTIFACT = "artifact"
    RESOURCE = "resource"
    SESSION = "session"
    EFFECT = "effect"
    DIAGNOSTIC = "diagnostic"
