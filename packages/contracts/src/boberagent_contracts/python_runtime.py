"""E5-A immutable claims for a future Python Resource; no runtime or authority issuer.

Reservation bindings deliberately contain no invented interpreter evidence. Sealed
bindings, historical verification and current validity are separate values. Even VALID
and READY claims do not authenticate a caller or authorize acquired-code execution.
"""

import re
from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BeforeValidator, ConfigDict, Field, StrictInt, model_validator

from ._base import FrozenContractModel, NonEmptyStr, SymbolicName
from .artifact import Sha256Digest
from .plan_canonical import canonical_digest
from .refs import ArtifactRef, CapabilityRunRef, DomainRef, PreparationPermitRef, ResourceRef
from .runtime_preparation import (
    ConfinementFeature,
    InterpreterEvidence,
    PreparationPermit,
    PreparationReasonCode,
    PreparationUsage,
    RuntimePreparationSpec,
    preparation_permit_digest,
)


def _logical_only(value: object) -> object:
    # Existing refs remain unchanged. This boundary excludes host-path-shaped claims.
    if isinstance(value, str) and ("/" in value or "\\" in value or ":" in value[:2]):
        raise ValueError("runtime identity must be a logical reference, not a host path")
    return value


def _boolean_fact(value: object) -> object:
    if type(value) is not bool:
        raise ValueError("evidence boolean must be a JSON boolean, not a numeric alias")
    return value


def _zero_swap(value: object) -> object:
    if type(value) is not int or value != 0:
        raise ValueError("swap limit must be integer zero")
    return value


type RuntimeResourceRef = Annotated[ResourceRef, BeforeValidator(_logical_only)]
type RuntimeCorrelation = Annotated[DomainRef, BeforeValidator(_logical_only)]
type Count = Annotated[StrictInt, Field(ge=0)]
type Limit = Annotated[StrictInt, Field(gt=0)]
type FalseFact = Annotated[Literal[False], BeforeValidator(_boolean_fact)]
type TrueFact = Annotated[Literal[True], BeforeValidator(_boolean_fact)]


class PythonRuntimeModel(FrozenContractModel):
    """Strict new E5 decoding; existing E1 model semantics remain unchanged."""

    model_config = ConfigDict(strict=True)


class PythonProviderOperation(StrEnum):
    INSPECT_INTERPRETER = "inspect_interpreter"
    CREATE_EMPTY_ENVIRONMENT = "create_empty_environment"
    VERIFY_ENVIRONMENT = "verify_environment"
    REVALIDATE = "revalidate"
    RELEASE = "release"


class PythonResourceState(StrEnum):
    """Same vocabulary as Node ResourceRuntimeState, not a transition engine."""

    CREATING = "CREATING"
    READY = "READY"
    FAILED = "FAILED"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    LOST = "LOST"


class PythonProviderPhase(StrEnum):
    RESERVED = "RESERVED"
    BUILDING = "BUILDING"
    VERIFYING = "VERIFYING"
    PUBLISHED = "PUBLISHED"
    QUARANTINED = "QUARANTINED"
    REMOVED = "REMOVED"


class PythonRuntimeValidity(StrEnum):
    UNCHECKED = "UNCHECKED"
    VALID = "VALID"
    INVALID = "INVALID"


class PythonRuntimeReason(StrEnum):
    PYTHON_RUNTIME_UNAVAILABLE = "PYTHON_RUNTIME_UNAVAILABLE"
    PYTHON_RUNTIME_MISMATCH = "PYTHON_RUNTIME_MISMATCH"
    PROCESS_LIMIT_UNAVAILABLE = "PROCESS_LIMIT_UNAVAILABLE"
    MEMORY_LIMIT_UNAVAILABLE = "MEMORY_LIMIT_UNAVAILABLE"
    STORAGE_LIMIT_UNAVAILABLE = "STORAGE_LIMIT_UNAVAILABLE"
    DESCENDANT_CONTAINMENT_UNAVAILABLE = "DESCENDANT_CONTAINMENT_UNAVAILABLE"
    RUNTIME_LIMIT_UNAVAILABLE = "RUNTIME_LIMIT_UNAVAILABLE"
    DEPENDENCY_INSTALL_FORBIDDEN = "DEPENDENCY_INSTALL_FORBIDDEN"
    VENV_CREATION_FAILED = "VENV_CREATION_FAILED"
    RUNTIME_INTEGRITY_FAILURE = "RUNTIME_INTEGRITY_FAILURE"
    RUNTIME_IDENTITY_CONFLICT = "RUNTIME_IDENTITY_CONFLICT"
    RUNTIME_REVALIDATION_FAILED = "RUNTIME_REVALIDATION_FAILED"
    RUNTIME_QUARANTINED = "RUNTIME_QUARANTINED"

    @property
    def preparation_reason(self) -> PreparationReasonCode:
        if self in {self.PYTHON_RUNTIME_UNAVAILABLE, self.VENV_CREATION_FAILED}:
            return PreparationReasonCode.RUNTIME_UNAVAILABLE
        if self is self.PYTHON_RUNTIME_MISMATCH:
            return PreparationReasonCode.NODE_CAPABILITY_MISMATCH
        if self is self.DEPENDENCY_INSTALL_FORBIDDEN:
            return PreparationReasonCode.DEPENDENCY_POLICY_DENIED
        if self is self.RUNTIME_QUARANTINED:
            return PreparationReasonCode.PREPARATION_INTERRUPTED
        if self in {
            self.RUNTIME_INTEGRITY_FAILURE,
            self.RUNTIME_IDENTITY_CONFLICT,
            self.RUNTIME_REVALIDATION_FAILED,
        }:
            return PreparationReasonCode.PREPARED_CONTENT_MISMATCH
        return PreparationReasonCode.CONFINEMENT_UNAVAILABLE


class PythonRuntimeFailure(PythonRuntimeModel):
    """Optional narrow detail alongside the existing E1 authority/resource reasons."""

    reason_code: PreparationReasonCode
    runtime_reason: PythonRuntimeReason | None = None

    @model_validator(mode="after")
    def matching_reason(self) -> Self:
        if self.runtime_reason and self.reason_code != self.runtime_reason.preparation_reason:
            raise ValueError("runtime reason does not match its E1 reason category")
        return self


class PythonRuntimeProfileIdentity(PythonRuntimeModel):
    profile_id: Literal["m20-e-python-stdlib-kali"]
    profile_version: Literal["1"]
    profile_sha256: Sha256Digest
    runtime_provider: Literal["python-stdlib@1"]
    construction_version: Literal["python-stdlib@1"]
    layout_version: Literal["m20-e5-python-layout@1"]


class PythonRuntimeRequestBinding(PythonRuntimeModel):
    """Immutable request pins, before interpreter/backend facts are known."""

    schema_version: Literal["python-runtime-request-binding-v1"]
    spec: RuntimePreparationSpec
    permit_ref: PreparationPermitRef
    permit_sha256: Sha256Digest
    run_ref: CapabilityRunRef
    materialization_id: RuntimeCorrelation
    source_tree_sha256: Sha256Digest
    entrypoint_sha256: Sha256Digest
    profile: PythonRuntimeProfileIdentity

    @model_validator(mode="after")
    def exact_profile_and_entrypoint(self) -> Self:
        if self.entrypoint_sha256 != self.spec.entrypoint.entry_sha256:
            raise ValueError("E4 entrypoint does not match preparation intent")
        if (
            self.profile.profile_id != self.spec.profile.profile_id
            or self.profile.profile_version != self.spec.profile.profile_version
            or self.profile.profile_sha256 != self.spec.profile_sha256
        ):
            raise ValueError("runtime profile identity does not match preparation intent")
        for ref in (
            self.spec.preparation_ref,
            self.spec.mission_ref,
            self.spec.plan_ref,
            self.permit_ref,
            self.run_ref,
            self.spec.source.plan_source.raw_artifact_ref,
            self.spec.source.plan_source.manifest_artifact_ref,
        ):
            _logical_only(ref)
        return self


class PythonRuntimeAuthorityProjection(PythonRuntimeModel):
    """Consistent serialized E2 claims, NOT a trusted Node admission handle."""

    permit: PreparationPermit
    binding: PythonRuntimeRequestBinding

    @model_validator(mode="after")
    def matching_permit(self) -> Self:
        if (
            self.binding.spec != self.permit.spec
            or self.binding.permit_ref != self.permit.permit_ref
            or self.binding.run_ref != self.permit.run_ref
            or self.binding.permit_sha256 != preparation_permit_digest(self.permit)
        ):
            raise ValueError("runtime binding does not match PreparationPermit")
        return self


class PythonRuntimeProjectionProfile(PythonRuntimeModel):
    """Closed initial executable view; not caller-provided exclusion rules."""

    profile_id: Literal["m20-e5-python-runtime-profile"] = "m20-e5-python-runtime-profile"
    profile_version: Literal["1"] = "1"
    required: tuple[
        Literal["INTERPRETER", "CORE_STDLIB", "STDLIB_EXTENSIONS", "VENV", "SHARED_CLOSURE"], ...
    ] = ("INTERPRETER", "CORE_STDLIB", "STDLIB_EXTENSIONS", "VENV", "SHARED_CLOSURE")
    supported_optional: tuple[Literal["NON_GUI_STDLIB"], ...] = ("NON_GUI_STDLIB",)
    unsupported_optional: tuple[Literal["TKINTER_TCL_TK", "PACKAGE_MANAGER"], ...] = (
        "TKINTER_TCL_TK",
        "PACKAGE_MANAGER",
    )

    @model_validator(mode="after")
    def closed_features(self) -> Self:
        if (
            self.required
            != ("INTERPRETER", "CORE_STDLIB", "STDLIB_EXTENSIONS", "VENV", "SHARED_CLOSURE")
            or self.supported_optional != ("NON_GUI_STDLIB",)
            # The explicit Tk-only shape remains decodable as historical evidence.
            # Fresh inventory always emits both features. Their exact membership
            # is hash-bound: old pins cannot authorize the refined executable view.
            or self.unsupported_optional
            not in {("TKINTER_TCL_TK",), ("TKINTER_TCL_TK", "PACKAGE_MANAGER")}
        ):
            raise ValueError("unsupported Python projection feature selection")
        return self


class PythonRuntimeProjectionIdentity(PythonRuntimeModel):
    profile: PythonRuntimeProjectionProfile
    profile_sha256: Sha256Digest
    base_manifest_sha256: Sha256Digest
    selected_manifest_sha256: Sha256Digest
    excluded_manifest_sha256: Sha256Digest
    projection_sha256: Sha256Digest

    @model_validator(mode="after")
    def pinned_profile(self) -> Self:
        if self.profile_sha256 != canonical_digest(
            self.profile
        ) or self.projection_sha256 != canonical_digest(
            self, exclude=frozenset({"projection_sha256"})
        ):
            raise ValueError("Python projection identity mismatch")
        return self


class _PythonDistributionPins(PythonRuntimeModel):
    """Logical pins, not a host path, installer attestation, readiness or authority."""

    provisioning: Literal["OPERATOR_PREPROVISIONED_UV"]
    interpreter_relative_path: Literal["bin/python3.12"]
    manifest_sha256: Sha256Digest
    root_binding_sha256: Sha256Digest
    support_manifest_sha256: Sha256Digest
    metadata_sha256: Sha256Digest | None
    entry_count: Limit
    runtime_bytes: Limit


class PythonDistributionIdentity(_PythonDistributionPins):
    """Historical full-tree v1 evidence; never reinterpreted as a projection."""

    manifest_version: Literal["m20-e5-python-distribution@1"]


class PythonProjectedDistributionIdentity(_PythonDistributionPins):
    manifest_version: Literal["m20-e5-python-distribution@2"]
    projection: PythonRuntimeProjectionIdentity


type PythonDistributionEvidence = PythonDistributionIdentity | PythonProjectedDistributionIdentity


class PythonInterpreterIdentity(PythonRuntimeModel):
    summary: InterpreterEvidence
    implementation: Literal["CPython"]
    build_identity: NonEmptyStr
    architecture: Literal["x86_64"]
    soabi: SymbolicName
    cache_tag: Literal["cpython-312"]
    base_layout: Literal["m20-e5-system-python@1", "m20-e5-uv-python@1"]
    stdlib_layout: Literal["m20-e5-system-stdlib@1", "m20-e5-uv-stdlib@1"]
    closure_sha256: Sha256Digest
    distribution: PythonDistributionEvidence | None = None

    @model_validator(mode="after")
    def admitted_interpreter(self) -> Self:
        if (
            self.summary.registry_tool != "python-runtime-3.12"
            or re.fullmatch(r"3\.12\.[0-9]+", self.summary.python_version) is None
            or self.summary.platform != "linux"
            or self.summary.abi != "cpython-312"
        ):
            raise ValueError("interpreter does not satisfy the pinned CPython 3.12 profile")
        if self.base_layout == "m20-e5-uv-python@1":
            if (
                self.stdlib_layout != "m20-e5-uv-stdlib@1"
                or self.distribution is None
                or self.closure_sha256 != self.distribution.manifest_sha256
                or self.summary.runtime_fingerprint != self.closure_sha256
            ):
                raise ValueError("selected distribution requires exact closure pins")
        elif self.distribution is not None or self.stdlib_layout != "m20-e5-system-stdlib@1":
            raise ValueError("incompatible distribution layout")
        return self


class PythonBackendIdentity(PythonRuntimeModel):
    backend_id: Literal["linux-bwrap-cgroup"]
    backend_version: Literal["1"]
    profile_id: Literal["m20-e5-linux-bwrap-cgroup"]
    profile_version: Literal["1"]
    profile_sha256: Sha256Digest
    binary_sha256: Sha256Digest
    binary_version: NonEmptyStr
    helper_sha256: Sha256Digest


class PythonRuntimeBinding(PythonRuntimeModel):
    """Sealed historical Resource identity; deliberately contains no readiness field."""

    schema_version: Literal["python-runtime-binding-v1"]
    resource_ref: RuntimeResourceRef
    request: PythonRuntimeRequestBinding
    interpreter: PythonInterpreterIdentity
    backend: PythonBackendIdentity


class PythonRuntimeCurrentState(PythonRuntimeModel):
    resource_ref: RuntimeResourceRef
    binding_sha256: Sha256Digest
    state: PythonResourceState
    phase: PythonProviderPhase
    validity: PythonRuntimeValidity
    checked_at: AwareDatetime | None = None
    boot_generation: RuntimeCorrelation | None = None
    failure: PythonRuntimeFailure | None = None

    @model_validator(mode="after")
    def current_verification(self) -> Self:
        if self.validity is not PythonRuntimeValidity.UNCHECKED:
            if self.checked_at is None or self.boot_generation is None:
                raise ValueError("checked validity requires time and Node generation")
        elif self.checked_at is not None or self.boot_generation is not None:
            raise ValueError("UNCHECKED cannot carry current verification claims")
        if self.validity is PythonRuntimeValidity.VALID and (
            self.state is not PythonResourceState.READY
            or self.phase is not PythonProviderPhase.PUBLISHED
            or self.failure is not None
        ):
            raise ValueError("VALID requires a published READY claim without failure")
        if self.validity is PythonRuntimeValidity.INVALID and self.failure is None:
            raise ValueError("INVALID requires a typed failure")
        return self


class PythonEnvironmentInventory(PythonRuntimeModel):
    namespace_prefix: Literal["/work/venv"]
    pyvenv_config_sha256: Sha256Digest
    inventory_sha256: Sha256Digest
    file_count: Count
    total_bytes: Count
    copied_executable_sha256: Sha256Digest
    permitted_links: tuple[Literal["lib64->lib"], ...] = Field(max_length=1)
    system_site_packages: FalseFact
    pip_bootstrapped: FalseFact
    pip_used: FalseFact
    external_installed_dependencies: tuple[()] = ()


class PythonRuntimeNonActions(PythonRuntimeModel):
    source_imported: FalseFact
    source_compiled: FalseFact
    entrypoint_executed: FalseFact
    package_installed: FalseFact
    activation_script_sourced: FalseFact
    target_secret_grants: tuple[()] = ()
    preparation_network: Literal["NONE"]


class PythonWritableMount(PythonRuntimeModel):
    namespace_path: Literal["/work/venv", "/work/tmp", "/work/home"]
    mechanism: Literal["SIZED_INODE_BOUNDED_TMPFS"]
    max_bytes: Limit
    max_inodes: Limit


class PythonRuntimeEnforcement(PythonRuntimeModel):
    """Measured proof claims; merely decoding them proves no live host control."""

    kernel_version: NonEmptyStr
    boot_generation: RuntimeCorrelation
    verified_features: tuple[ConfinementFeature, ...] = Field(
        json_schema_extra={"collection_semantics": "set"}
    )
    process_mechanism: Literal["CGROUP_V2_PIDS_MAX"]
    memory_mechanism: Literal["CGROUP_V2_MEMORY_MAX_ZERO_SWAP_GROUP_OOM"]
    descendant_mechanism: Literal["CGROUP_KILL_SUPERVISED_PID_NAMESPACE"]
    storage_mechanism: Literal["CAPPED_TMPFS_BOUNDED_TRUSTED_PUBLISHER"]
    runtime_mechanism: Literal["SUPERVISED_MONOTONIC_DEADLINES"]
    output_mechanism: Literal["COMBINED_CAPPED_PIPE_DRAIN"]
    network_mechanism: Literal["EMPTY_NETWORK_NAMESPACE_NO_SOCKET_FDS"]
    filesystem_policy: Literal["MINIMAL_READONLY_VIEW_NO_WRITABLE_HOST_BIND"]
    source_visibility: Literal["ABSENT_DURING_PYTHON_OPERATIONS"]
    effective_process_limit: Limit
    effective_memory_bytes: Limit
    effective_swap_bytes: Annotated[Literal[0], BeforeValidator(_zero_swap)]
    effective_process_seconds: Limit
    effective_total_seconds: Limit
    effective_output_bytes: Limit
    effective_write_bytes: Limit
    writable_mounts: tuple[PythonWritableMount, ...] = Field(min_length=1, max_length=3)
    passed_probes: tuple[ConfinementFeature, ...] = Field(
        json_schema_extra={"collection_semantics": "set"}
    )
    pids_limit_events: Count
    oom_events: Count
    memory_peak_bytes: Count
    processes_peak: Count
    descendants_empty: TrueFact

    @model_validator(mode="after")
    def complete_proof(self) -> Self:
        for values in (self.verified_features, self.passed_probes):
            if len(values) != len(ConfinementFeature) or set(values) != set(ConfinementFeature):
                raise ValueError("all twelve distinct controls and probes are required")
        paths = [mount.namespace_path for mount in self.writable_mounts]
        if set(paths) != {"/work/venv", "/work/tmp", "/work/home"} or len(paths) != 3:
            raise ValueError("exact fixed writable mount inventory required")
        if self.pids_limit_events or self.oom_events:
            raise ValueError("limit/oom events invalidate positive verification")
        if (
            self.memory_peak_bytes > self.effective_memory_bytes
            or self.processes_peak > self.effective_process_limit
        ):
            raise ValueError("measured peaks exceed effective limits")
        return self


class PythonRuntimeOutputEvidence(PythonRuntimeModel):
    stdout_bytes: Count
    stdout_sha256: Sha256Digest
    stderr_bytes: Count
    stderr_sha256: Sha256Digest


class PythonRuntimeEvidence(PythonRuntimeModel):
    """Intermediate immutable E5 evidence, never the final E6 receipt or authority."""

    schema_version: Literal["PythonRuntimeEvidence-v1"]
    binding: PythonRuntimeBinding
    workspace_correlation: RuntimeCorrelation
    operation: PythonProviderOperation
    environment: PythonEnvironmentInventory | None
    non_actions: PythonRuntimeNonActions
    enforcement: PythonRuntimeEnforcement | None
    aggregate_usage: PreparationUsage
    e5_usage: PreparationUsage
    budget_ledger_correlation: RuntimeCorrelation
    outputs: PythonRuntimeOutputEvidence
    started_at: AwareDatetime
    completed_at: AwareDatetime
    monotonic_duration_milliseconds: Count
    verification: Literal["VERIFIED", "PROVENANCE_VERIFIED", "REJECTED"]
    failure: PythonRuntimeFailure | None
    evidence_artifact_refs: tuple[ArtifactRef, ...] = Field(
        max_length=64, json_schema_extra={"collection_semantics": "set"}
    )

    @model_validator(mode="after")
    def verified_claim(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("runtime evidence timestamps out of order")
        if self.started_at.utcoffset() != timedelta(
            0
        ) or self.completed_at.utcoffset() != timedelta(0):
            raise ValueError("runtime evidence must use UTC timestamps")
        if self.verification == "REJECTED":
            if self.failure is None:
                raise ValueError("rejected evidence requires a typed reason")
            return self
        if self.verification == "PROVENANCE_VERIFIED":
            if (
                self.operation is not PythonProviderOperation.INSPECT_INTERPRETER
                or self.binding.interpreter.distribution is None
                or self.environment is not None
                or self.enforcement is None
                or self.failure is not None
            ):
                raise ValueError(
                    "provenance is interpreter inspection, not environment verification"
                )
        elif self.failure is not None or self.environment is None or self.enforcement is None:
            raise ValueError("verified evidence requires environment and enforcement, no failure")
        elif self.operation not in {
            PythonProviderOperation.VERIFY_ENVIRONMENT,
            PythonProviderOperation.REVALIDATE,
        }:
            raise ValueError("only verification/revalidation can report VERIFIED")
        if self.environment is not None and (
            self.environment.copied_executable_sha256
            != self.binding.interpreter.summary.executable_sha256
        ):
            raise ValueError("copied interpreter identity mismatch")
        budgets = self.binding.request.spec.budgets
        usage_limits = {
            "imported_bytes": budgets.max_imported_artifact_bytes,
            "materialized_bytes": budgets.max_materialized_bytes,
            "file_count": budgets.max_file_count,
            "temporary_bytes": budgets.max_temporary_bytes,
            "preparation_write_bytes": budgets.max_preparation_write_bytes,
            "peak_processes": budgets.max_processes,
            "process_runtime_seconds": budgets.max_process_runtime_seconds,
            "total_runtime_seconds": budgets.max_total_runtime_seconds,
            "captured_output_bytes": budgets.max_captured_output_bytes,
            "peak_memory_bytes": budgets.max_memory_bytes,
        }
        for field, limit in usage_limits.items():
            aggregate = getattr(self.aggregate_usage, field)
            if aggregate > limit or getattr(self.e5_usage, field) > aggregate:
                raise ValueError("aggregate/E5 usage does not fit admitted budgets")
        proof = self.enforcement
        assert proof is not None
        for actual, maximum in (
            (proof.effective_process_limit, budgets.max_processes),
            (proof.effective_memory_bytes, budgets.max_memory_bytes),
            (proof.effective_process_seconds, budgets.max_process_runtime_seconds),
            (proof.effective_total_seconds, budgets.max_total_runtime_seconds),
            (proof.effective_output_bytes, budgets.max_captured_output_bytes),
            (proof.effective_write_bytes, budgets.max_preparation_write_bytes),
            (sum(m.max_bytes for m in proof.writable_mounts), budgets.max_temporary_bytes),
        ):
            if actual > maximum:
                raise ValueError("effective enforcement exceeds admitted budget")
        if (
            self.outputs.stdout_bytes + self.outputs.stderr_bytes
            > self.e5_usage.captured_output_bytes
        ):
            raise ValueError("captured output not charged to usage")
        if (
            proof.memory_peak_bytes > self.e5_usage.peak_memory_bytes
            or proof.processes_peak > self.e5_usage.peak_processes
            or self.monotonic_duration_milliseconds > self.e5_usage.total_runtime_seconds * 1000
            or (
                self.environment is not None
                and self.environment.total_bytes > self.e5_usage.preparation_write_bytes
            )
        ):
            raise ValueError("measured runtime facts not charged to usage")
        if len(set(self.evidence_artifact_refs)) != len(self.evidence_artifact_refs):
            raise ValueError("duplicate evidence Artifact refs")
        for ref in self.evidence_artifact_refs:
            _logical_only(ref)
        return self


def python_runtime_request_digest(binding: PythonRuntimeRequestBinding) -> Sha256Digest:
    return canonical_digest(binding)


def python_runtime_binding_digest(binding: PythonRuntimeBinding) -> Sha256Digest:
    return canonical_digest(binding)


def python_runtime_evidence_digest(evidence: PythonRuntimeEvidence) -> Sha256Digest:
    return canonical_digest(evidence)
