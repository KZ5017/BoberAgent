"""Immutable M20-E preparation intent, claimed authority, and observed evidence.

These values neither issue a permit nor authenticate its issuer. Core admission and trusted
Node transport admission belong to later slices. No model here can authorize PoC execution.
"""

from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StringConstraints, model_validator

from ._base import FrozenContractModel, NonEmptyStr, SymbolicName
from .artifact import Sha256Digest
from .plan_canonical import canonical_digest
from .plan_requirements import ExecutionLocation, PlanSource, RuntimeRequirement
from .plan_values import EntrypointIntent
from .refs import (
    ArtifactRef,
    CapabilityRunRef,
    ExecutionPlanRef,
    MissionRef,
    PlanDecisionRef,
    PreparationPermitRef,
    ResourceRef,
    RuntimePreparationManifestRef,
    RuntimePreparationRef,
)
from .version import VersionString

RUNTIME_PREPARATION_CAPABILITY_ID = "runtime.prepare"
RUNTIME_PREPARATION_OPERATION = "prepare"

type PreparationNodeId = Annotated[
    str,
    StringConstraints(min_length=3, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]


class PreparationAction(StrEnum):
    IMPORT_AUTHORIZED_ARTIFACT = "IMPORT_AUTHORIZED_ARTIFACT"
    VERIFY_ARTIFACT = "VERIFY_ARTIFACT"
    MATERIALIZE_SOURCE = "MATERIALIZE_SOURCE"
    CREATE_RUNTIME_RESOURCE = "CREATE_RUNTIME_RESOURCE"
    INSPECT_TRUSTED_INTERPRETER = "INSPECT_TRUSTED_INTERPRETER"
    CREATE_EMPTY_PYTHON_ENVIRONMENT = "CREATE_EMPTY_PYTHON_ENVIRONMENT"
    VERIFY_PYTHON_ENVIRONMENT = "VERIFY_PYTHON_ENVIRONMENT"
    WRITE_PREPARATION_EVIDENCE = "WRITE_PREPARATION_EVIDENCE"
    QUARANTINE_OWN_PARTIAL_STATE = "QUARANTINE_OWN_PARTIAL_STATE"
    CLEANUP_OWN_PREPARATION_STATE = "CLEANUP_OWN_PREPARATION_STATE"


class ConfinementFeature(StrEnum):
    NO_SUBPROCESS_NETWORK = "NO_SUBPROCESS_NETWORK"
    NO_INHERITED_SOCKETS = "NO_INHERITED_SOCKETS"
    NO_HOST_CONTROL_SOCKETS = "NO_HOST_CONTROL_SOCKETS"
    BOUNDED_WRITABLE_FILESYSTEM = "BOUNDED_WRITABLE_FILESYSTEM"
    MANAGED_SOURCE_VISIBILITY = "MANAGED_SOURCE_VISIBILITY"
    PROCESS_LIMIT = "PROCESS_LIMIT"
    MEMORY_LIMIT = "MEMORY_LIMIT"
    RUNTIME_LIMIT = "RUNTIME_LIMIT"
    OUTPUT_LIMIT = "OUTPUT_LIMIT"
    STORAGE_LIMIT = "STORAGE_LIMIT"
    DESCENDANT_CONTAINMENT = "DESCENDANT_CONTAINMENT"
    NO_ARBITRARY_HOST_FILESYSTEM = "NO_ARBITRARY_HOST_FILESYSTEM"


class PreparationReasonCategory(StrEnum):
    AUTHORITY = "AUTHORITY"
    UNSUPPORTED = "UNSUPPORTED"
    INTEGRITY = "INTEGRITY"
    RUNTIME_PREREQUISITE = "RUNTIME_PREREQUISITE"
    RESOURCE = "RESOURCE"
    RECOVERY = "RECOVERY"
    CANCELLATION = "CANCELLATION"


class PreparationReasonCode(StrEnum):
    PREPARATION_NOT_AUTHORIZED = "PREPARATION_NOT_AUTHORIZED"
    AUTHORITY_STALE = "AUTHORITY_STALE"
    POLICY_DENIED = "POLICY_DENIED"
    APPROVAL_INAPPLICABLE = "APPROVAL_INAPPLICABLE"
    DEPENDENCY_POLICY_DENIED = "DEPENDENCY_POLICY_DENIED"
    BUILD_UNSUPPORTED = "BUILD_UNSUPPORTED"
    SECRET_REQUIREMENT_UNSUPPORTED = "SECRET_REQUIREMENT_UNSUPPORTED"
    SOURCE_INTEGRITY_FAILURE = "SOURCE_INTEGRITY_FAILURE"
    MANIFEST_MISMATCH = "MANIFEST_MISMATCH"
    PREPARED_CONTENT_MISMATCH = "PREPARED_CONTENT_MISMATCH"
    RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
    NODE_CAPABILITY_MISMATCH = "NODE_CAPABILITY_MISMATCH"
    CONFINEMENT_UNAVAILABLE = "CONFINEMENT_UNAVAILABLE"
    WORKSPACE_LIMIT_EXCEEDED = "WORKSPACE_LIMIT_EXCEEDED"
    PREPARATION_TIMEOUT = "PREPARATION_TIMEOUT"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    PREPARATION_INTERRUPTED = "PREPARATION_INTERRUPTED"
    PREPARATION_CANCELLED = "PREPARATION_CANCELLED"

    @property
    def category(self) -> PreparationReasonCategory:
        if self in {
            self.PREPARATION_NOT_AUTHORIZED,
            self.AUTHORITY_STALE,
            self.POLICY_DENIED,
            self.APPROVAL_INAPPLICABLE,
        }:
            return PreparationReasonCategory.AUTHORITY
        if self in {
            self.DEPENDENCY_POLICY_DENIED,
            self.BUILD_UNSUPPORTED,
            self.SECRET_REQUIREMENT_UNSUPPORTED,
        }:
            return PreparationReasonCategory.UNSUPPORTED
        if self in {
            self.SOURCE_INTEGRITY_FAILURE,
            self.MANIFEST_MISMATCH,
            self.PREPARED_CONTENT_MISMATCH,
        }:
            return PreparationReasonCategory.INTEGRITY
        if self in {
            self.RUNTIME_UNAVAILABLE,
            self.NODE_CAPABILITY_MISMATCH,
            self.CONFINEMENT_UNAVAILABLE,
        }:
            return PreparationReasonCategory.RUNTIME_PREREQUISITE
        if self in {
            self.WORKSPACE_LIMIT_EXCEEDED,
            self.PREPARATION_TIMEOUT,
            self.STORAGE_UNAVAILABLE,
        }:
            return PreparationReasonCategory.RESOURCE
        if self is self.PREPARATION_INTERRUPTED:
            return PreparationReasonCategory.RECOVERY
        return PreparationReasonCategory.CANCELLATION


class PreparationOutcome(StrEnum):
    PREPARED = "PREPARED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"


class ConfinementRequirement(FrozenContractModel):
    """Closed baseline property set; no backend or claimed verification lives here."""

    required_features: tuple[ConfinementFeature, ...] = Field(
        min_length=len(ConfinementFeature), json_schema_extra={"collection_semantics": "set"}
    )

    @model_validator(mode="after")
    def complete_baseline(self) -> Self:
        if len(self.required_features) != len(ConfinementFeature) or set(
            self.required_features
        ) != set(ConfinementFeature):
            raise ValueError("baseline confinement requires every defined feature exactly once")
        return self


class PreparationNetworkPolicy(FrozenContractModel):
    infrastructure: Literal["CONTROL_AND_AUTHORIZED_IMPORT_ONLY"]
    subprocess_network: Literal["DENY"]
    package_network: Literal["DENY"]
    target_network: Literal["DENY"]
    listener_session_network: Literal["DENY"]


class PreparationSecretPolicy(FrozenContractModel):
    target_secret_grants: Literal["DENY"]
    target_secret_resolution: Literal["DENY"]


class InitialPythonPreparationProfile(FrozenContractModel):
    profile_id: Literal["m20-e-python-stdlib-kali"]
    profile_version: Literal["1"]
    location: Literal["ATTACKER_KALI"]
    runtime_kind: Literal["python"]
    python_family: Literal["3.12"]
    dependency_policy: Literal["STDLIB_ONLY"]
    external_dependency_installation: Literal["DENY"]
    pip: Literal["DENY"]
    source_modification: Literal["DENY"]
    source_import: Literal["DENY"]
    entrypoint_execution: Literal["DENY"]
    user_space: Literal[True]
    noninteractive: Literal[True]
    single_target: Literal[True]
    network: PreparationNetworkPolicy
    secrets: PreparationSecretPolicy
    confinement: ConfinementRequirement


def initial_python_preparation_profile() -> InitialPythonPreparationProfile:
    """Construct the fully explicit, immutable v1 profile without caller-controlled knobs."""

    return InitialPythonPreparationProfile(
        profile_id="m20-e-python-stdlib-kali",
        profile_version="1",
        location="ATTACKER_KALI",
        runtime_kind="python",
        python_family="3.12",
        dependency_policy="STDLIB_ONLY",
        external_dependency_installation="DENY",
        pip="DENY",
        source_modification="DENY",
        source_import="DENY",
        entrypoint_execution="DENY",
        user_space=True,
        noninteractive=True,
        single_target=True,
        network=PreparationNetworkPolicy(
            infrastructure="CONTROL_AND_AUTHORIZED_IMPORT_ONLY",
            subprocess_network="DENY",
            package_network="DENY",
            target_network="DENY",
            listener_session_network="DENY",
        ),
        secrets=PreparationSecretPolicy(
            target_secret_grants="DENY", target_secret_resolution="DENY"
        ),
        confinement=ConfinementRequirement(required_features=tuple(ConfinementFeature)),
    )


class PreparationBudgets(FrozenContractModel):
    """Finite E-only limits; never reuse ExecutionPlan's later execution budgets."""

    max_imported_artifact_bytes: StrictInt = Field(ge=1, le=16 * 1024**3)
    max_materialized_bytes: StrictInt = Field(ge=1, le=64 * 1024**3)
    max_file_count: StrictInt = Field(ge=1, le=1_000_000)
    max_path_depth: StrictInt = Field(ge=1, le=256)
    max_temporary_bytes: StrictInt = Field(ge=1, le=64 * 1024**3)
    max_preparation_write_bytes: StrictInt = Field(ge=1, le=64 * 1024**3)
    max_processes: StrictInt = Field(ge=1, le=128)
    max_process_runtime_seconds: StrictInt = Field(ge=1, le=86_400)
    max_total_runtime_seconds: StrictInt = Field(ge=1, le=86_400)
    max_captured_output_bytes: StrictInt = Field(ge=1, le=1024**3)
    max_memory_bytes: StrictInt = Field(ge=1, le=1024**4)

    @model_validator(mode="after")
    def coherent_time(self) -> Self:
        if self.max_process_runtime_seconds > self.max_total_runtime_seconds:
            raise ValueError("per-process runtime cannot exceed total preparation runtime")
        return self


class PreparationSource(FrozenContractModel):
    plan_source: PlanSource
    manifest_size_bytes: StrictInt = Field(ge=0, le=16 * 1024**3)

    @model_validator(mode="after")
    def exact_retained_source(self) -> Self:
        if self.plan_source.resolved_commit is None:
            raise ValueError("preparation requires a resolved immutable commit")
        if self.plan_source.raw_artifact_ref == self.plan_source.manifest_artifact_ref:
            raise ValueError("raw and structural manifest Artifacts must differ")
        return self


class PreparationAuthorityBoundary(FrozenContractModel):
    """Explicit negative authority; cannot be widened by a serialized permit."""

    target_execution: Literal[False] = False
    entrypoint_launch: Literal[False] = False
    target_network: Literal[False] = False
    listener_or_session_creation: Literal[False] = False
    target_secret_resolution: Literal[False] = False
    package_installation_or_download: Literal[False] = False
    arbitrary_command_execution: Literal[False] = False


class RuntimePreparationSpec(FrozenContractModel):
    """Exact proposed preparation intent, not current Core admission or Node authority."""

    schema_version: Literal["runtime-preparation-spec-v1"]
    preparation_ref: RuntimePreparationRef
    mission_ref: MissionRef
    plan_ref: ExecutionPlanRef
    plan_intent_sha256: Sha256Digest
    node_id: PreparationNodeId
    provider_id: UUID
    provider_version: VersionString
    source: PreparationSource
    entrypoint: EntrypointIntent
    runtime: RuntimeRequirement
    profile: InitialPythonPreparationProfile
    profile_sha256: Sha256Digest
    budgets: PreparationBudgets
    allowed_actions: tuple[PreparationAction, ...] = Field(
        min_length=1, json_schema_extra={"collection_semantics": "set"}
    )

    @model_validator(mode="after")
    def baseline_shape(self) -> Self:
        if self.profile_sha256 != preparation_profile_digest(self.profile):
            raise ValueError("preparation profile digest does not match the profile")
        if self.source.plan_source.raw_size_bytes + self.source.manifest_size_bytes > (
            self.budgets.max_imported_artifact_bytes
        ):
            raise ValueError("retained Artifacts exceed the import budget")
        if len(self.allowed_actions) != len(set(self.allowed_actions)):
            raise ValueError("preparation actions must be unique")
        if (
            self.runtime.kind != "python"
            or self.runtime.platform != "LINUX"
            or self.runtime.platform_variant != "kali"
            or self.runtime.location is not ExecutionLocation.ATTACKER_NODE
            or not self.runtime.user_space
            or not self.runtime.noninteractive
            or self.entrypoint.language != "python"
            or self.entrypoint.invocation_form != "SCRIPT"
        ):
            raise ValueError("initial preparation requires attacker-side user-space Python")
        return self


class PreparationPermit(FrozenContractModel):
    """Core-issued claim, usable only after trusted admission by a future Node adapter."""

    schema_version: Literal["preparation-permit-v1"]
    permit_ref: PreparationPermitRef
    spec: RuntimePreparationSpec
    spec_sha256: Sha256Digest
    run_ref: CapabilityRunRef
    validation_decision_ref: PlanDecisionRef
    validation_sha256: Sha256Digest
    policy_decision_ref: PlanDecisionRef
    policy_context_sha256: Sha256Digest
    policy_decision: Literal["ALLOW", "REQUIRES_APPROVAL"]
    approval_decision_ref: PlanDecisionRef | None
    issued_at: AwareDatetime
    not_before: AwareDatetime
    expires_at: AwareDatetime
    admission_nonce: SymbolicName
    maximum_preparation_runs: Literal[1]
    boundary: PreparationAuthorityBoundary

    @model_validator(mode="after")
    def preparation_only(self) -> Self:
        if self.spec_sha256 != preparation_spec_fingerprint(self.spec):
            raise ValueError("permit does not bind the exact preparation spec")
        if (self.policy_decision == "REQUIRES_APPROVAL") != (
            self.approval_decision_ref is not None
        ):
            raise ValueError("approval identity must match the policy decision")
        if not self.issued_at <= self.not_before < self.expires_at:
            raise ValueError("permit validity interval is invalid")
        if self.expires_at - self.not_before > timedelta(days=1):
            raise ValueError("preparation permit validity exceeds one day")
        return self


class RuntimePreparationInput(FrozenContractModel):
    """Future `runtime.prepare` operation input; decoding grants no authority."""

    schema_version: Literal["runtime-preparation-input-v1"]
    permit: PreparationPermit


class PreparationUsage(FrozenContractModel):
    imported_bytes: StrictInt = Field(ge=0)
    materialized_bytes: StrictInt = Field(ge=0)
    file_count: StrictInt = Field(ge=0)
    temporary_bytes: StrictInt = Field(ge=0)
    preparation_write_bytes: StrictInt = Field(ge=0)
    peak_processes: StrictInt = Field(ge=0)
    process_runtime_seconds: StrictInt = Field(ge=0)
    total_runtime_seconds: StrictInt = Field(ge=0)
    captured_output_bytes: StrictInt = Field(ge=0)
    peak_memory_bytes: StrictInt = Field(ge=0)


class MaterializationEvidence(FrozenContractModel):
    verified: StrictBool
    file_count: StrictInt = Field(ge=0)
    total_bytes: StrictInt = Field(ge=0)
    tree_sha256: Sha256Digest
    entrypoint_sha256: Sha256Digest


class InterpreterEvidence(FrozenContractModel):
    registry_tool: SymbolicName
    executable_sha256: Sha256Digest
    python_version: VersionString
    platform: SymbolicName
    abi: SymbolicName
    runtime_fingerprint: Sha256Digest


class PythonEnvironmentEvidence(FrozenContractModel):
    system_site_packages: Literal[False]
    pip_bootstrapped: Literal[False]
    pip_used: Literal[False]
    source_imported: Literal[False]
    source_compiled: Literal[False]
    entrypoint_executed: Literal[False]


class FixedEnvironmentEvidence(FrozenContractModel):
    node_controlled_path: Literal[True]
    ambient_pythonpath: Literal[False]
    ambient_user_site: Literal[False]
    ambient_package_manager_config: Literal[False]
    activation_script_sourced: Literal[False]


class ConfinementEvidence(FrozenContractModel):
    backend_id: SymbolicName
    backend_version: NonEmptyStr
    profile_id: SymbolicName
    profile_version: NonEmptyStr
    verified_features: tuple[ConfinementFeature, ...] = Field(
        json_schema_extra={"collection_semantics": "set"}
    )

    @model_validator(mode="after")
    def unique_features(self) -> Self:
        if len(self.verified_features) != len(set(self.verified_features)):
            raise ValueError("verified confinement features must be unique")
        return self


class RuntimePreparationManifest(FrozenContractModel):
    """Node observation, not Core acceptance, hardware attestation or authorization."""

    schema_version: Literal["runtime-preparation-manifest-v1"]
    manifest_ref: RuntimePreparationManifestRef
    spec: RuntimePreparationSpec
    run_ref: CapabilityRunRef
    permit_ref: PreparationPermitRef
    permit_sha256: Sha256Digest
    resource_ref: ResourceRef | None
    workspace_correlation: SymbolicName | None
    materialization: MaterializationEvidence
    interpreter: InterpreterEvidence
    environment: PythonEnvironmentEvidence
    external_installed_dependencies: tuple[SymbolicName, ...]
    usage: PreparationUsage
    confinement: ConfinementEvidence
    fixed_environment: FixedEnvironmentEvidence
    started_at: AwareDatetime
    completed_at: AwareDatetime
    outcome: PreparationOutcome
    reason_code: PreparationReasonCode | None
    evidence_artifact_refs: tuple[ArtifactRef, ...] = Field(
        json_schema_extra={"collection_semantics": "set"}
    )

    @model_validator(mode="after")
    def evidence_shape(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("preparation completion precedes start")
        if self.outcome is PreparationOutcome.PREPARED:
            if self.reason_code is not None or self.resource_ref is None:
                raise ValueError("prepared outcome needs a Resource and no failure reason")
            if not self.workspace_correlation or not self.materialization.verified:
                raise ValueError("prepared outcome needs verified source and logical workspace")
            if self.external_installed_dependencies:
                raise ValueError("baseline preparation cannot install external dependencies")
            if set(self.confinement.verified_features) != set(
                self.spec.profile.confinement.required_features
            ):
                raise ValueError("prepared outcome needs every required confinement feature")
            limits = self.spec.budgets
            usage = self.usage
            if any(
                observed > maximum
                for observed, maximum in (
                    (usage.imported_bytes, limits.max_imported_artifact_bytes),
                    (usage.materialized_bytes, limits.max_materialized_bytes),
                    (usage.file_count, limits.max_file_count),
                    (usage.temporary_bytes, limits.max_temporary_bytes),
                    (usage.preparation_write_bytes, limits.max_preparation_write_bytes),
                    (usage.peak_processes, limits.max_processes),
                    (usage.process_runtime_seconds, limits.max_process_runtime_seconds),
                    (usage.total_runtime_seconds, limits.max_total_runtime_seconds),
                    (usage.captured_output_bytes, limits.max_captured_output_bytes),
                    (usage.peak_memory_bytes, limits.max_memory_bytes),
                )
            ):
                raise ValueError("prepared outcome exceeded a preparation budget")
            if self.materialization.entrypoint_sha256 != self.spec.entrypoint.entry_sha256:
                raise ValueError("prepared entrypoint hash differs from the plan")
            if (
                self.materialization.file_count != self.usage.file_count
                or self.materialization.total_bytes != self.usage.materialized_bytes
            ):
                raise ValueError("prepared source summary disagrees with observed usage")
        elif self.reason_code is None:
            raise ValueError("non-prepared outcome needs a typed reason")
        if len(self.evidence_artifact_refs) != len(set(self.evidence_artifact_refs)):
            raise ValueError("evidence ArtifactRefs must be unique")
        return self


class RuntimePreparationReceipt(FrozenContractModel):
    """Typed future Result detail; receipt does not establish Core Artifact availability."""

    schema_version: Literal["runtime-preparation-receipt-v1"]
    preparation_ref: RuntimePreparationRef
    run_ref: CapabilityRunRef
    resource_ref: ResourceRef | None
    manifest_ref: RuntimePreparationManifestRef
    manifest_artifact_ref: ArtifactRef
    manifest_sha256: Sha256Digest
    manifest_size_bytes: StrictInt = Field(ge=0)
    permit_ref: PreparationPermitRef
    permit_sha256: Sha256Digest
    node_id: PreparationNodeId
    provider_id: UUID
    provider_version: VersionString
    outcome: PreparationOutcome
    reason_code: PreparationReasonCode | None

    @model_validator(mode="after")
    def receipt_shape(self) -> Self:
        if self.outcome is PreparationOutcome.PREPARED:
            if self.resource_ref is None or self.reason_code is not None:
                raise ValueError("prepared receipt needs a Resource and no failure reason")
        elif self.reason_code is None:
            raise ValueError("non-prepared receipt needs a typed reason")
        return self


def preparation_profile_digest(profile: InitialPythonPreparationProfile) -> str:
    """Profile/config identity, not evidence that a provider satisfies the profile."""

    return canonical_digest(profile)


def preparation_spec_fingerprint(spec: RuntimePreparationSpec) -> str:
    """Semantic request identity; exclude only generated attempt reference."""

    return canonical_digest(spec, exclude=frozenset({"preparation_ref"}))


def preparation_permit_digest(permit: PreparationPermit) -> str:
    """Exact serialized authority claim identity, never authentication of its issuer."""

    return canonical_digest(permit)


def preparation_manifest_digest(manifest: RuntimePreparationManifest) -> str:
    """Exact immutable evidence identity, not Core acceptance or safety attestation."""

    return canonical_digest(manifest)
