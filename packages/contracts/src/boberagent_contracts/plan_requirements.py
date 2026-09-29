"""Immutable execution requirements; none allocate, install, resolve or authorize."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, StrictBool, StrictInt, model_validator

from ._base import FrozenContractModel, NonEmptyStr, SymbolicName
from .artifact import Sha256Digest
from .enums import AccessMode
from .plan_values import RelativeSourcePath, validate_relative_path
from .poc_acquisition import FullGitCommitSha
from .refs import (
    ArtifactRef,
    CredentialRef,
    PoCAcquisitionRef,
    ResourceRef,
    SecretRef,
    SessionRef,
)


class PlanSource(FrozenContractModel):
    acquisition_ref: PoCAcquisitionRef
    raw_artifact_ref: ArtifactRef
    raw_sha256: Sha256Digest
    raw_size_bytes: StrictInt = Field(ge=0)
    manifest_artifact_ref: ArtifactRef
    manifest_sha256: Sha256Digest
    resolved_commit: FullGitCommitSha | None = None


class ExecutionLocation(StrEnum):
    ATTACKER_NODE = "ATTACKER_NODE"
    TARGET = "TARGET"
    REMOTE_SESSION = "REMOTE_SESSION"
    UNKNOWN = "UNKNOWN"


class RuntimeRequirement(FrozenContractModel):
    kind: SymbolicName
    version_constraint: NonEmptyStr
    platform: Literal["LINUX", "WINDOWS", "OTHER", "UNKNOWN"]
    platform_variant: SymbolicName | None = None
    user_space: StrictBool
    noninteractive: StrictBool
    location: ExecutionLocation


class PlanDependencyKind(StrEnum):
    STDLIB_MODULE = "STDLIB_MODULE"
    LOCAL_MODULE = "LOCAL_MODULE"
    THIRD_PARTY_PACKAGE = "THIRD_PARTY_PACKAGE"
    SYSTEM_TOOL = "SYSTEM_TOOL"
    OS_BUILD = "OS_BUILD"
    RUNTIME_MODULE = "RUNTIME_MODULE"
    DOCUMENTATION_CLAIM = "DOCUMENTATION_CLAIM"
    UNKNOWN = "UNKNOWN"


class PlanDependency(FrozenContractModel):
    dependency_id: SymbolicName
    kind: PlanDependencyKind
    identifier: NonEmptyStr
    version_constraint: NonEmptyStr | None = None
    evidence_ids: tuple[SymbolicName, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )


class SecretRequirement(FrozenContractModel):
    kind: Literal["secret"] = "secret"
    secret_ref: SecretRef
    role: SymbolicName
    purpose: NonEmptyStr
    binding_id: SymbolicName


class CredentialRequirement(FrozenContractModel):
    kind: Literal["credential"] = "credential"
    credential_ref: CredentialRef
    role: SymbolicName
    purpose: NonEmptyStr
    binding_id: SymbolicName


class ResourceRequirement(FrozenContractModel):
    requirement_id: SymbolicName
    resource_type: SymbolicName
    purpose: NonEmptyStr
    access_mode: AccessMode
    existing_ref: ResourceRef | None = None


class SessionRequirement(FrozenContractModel):
    requirement_id: SymbolicName
    session_type: SymbolicName
    purpose: NonEmptyStr
    access_mode: AccessMode
    existing_ref: SessionRef | None = None
    resource_requirement_id: SymbolicName | None = None


class EffectScope(StrEnum):
    BOUNDED = "BOUNDED"
    UNKNOWN = "UNKNOWN"
    BROAD = "BROAD"


class FilesystemOperation(StrEnum):
    READ = "READ"
    WRITE = "WRITE"
    CREATE = "CREATE"
    DELETE = "DELETE"


class FilesystemRule(FrozenContractModel):
    root_requirement_id: SymbolicName
    relative_path: RelativeSourcePath
    match: Literal["EXACT", "PATTERN"] = "EXACT"
    operations: tuple[FilesystemOperation, ...] = Field(
        min_length=1, json_schema_extra={"collection_semantics": "set"}
    )

    @model_validator(mode="after")
    def shape(self) -> Self:
        validate_relative_path(self.relative_path)
        if self.match == "EXACT" and any(char in self.relative_path for char in "*?["):
            raise ValueError("wildcard requires explicit PATTERN semantics")
        return self


class FilesystemConstraints(FrozenContractModel):
    source_read_only: Literal[True] = True
    writable_root_requirement_id: SymbolicName | None = None
    scope: EffectScope
    rules: tuple[FilesystemRule, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    cleanup: Literal["REMOVE_MANAGED_WRITES", "RETAIN_EVIDENCE", "OPERATOR_REVIEW"]

    @model_validator(mode="after")
    def shape(self) -> Self:
        for rule in self.rules:
            if any(op is not FilesystemOperation.READ for op in rule.operations) and (
                self.writable_root_requirement_id != rule.root_requirement_id
            ):
                raise ValueError("writes require the declared managed writable root")
        return self


class NetworkDestinationClass(StrEnum):
    SELECTED_TARGET = "SELECTED_TARGET"
    CALLBACK = "CALLBACK"
    LISTENER_BIND = "LISTENER_BIND"
    PUBLIC_INTERNET = "PUBLIC_INTERNET"
    PREPARATION_EGRESS = "PREPARATION_EGRESS"
    MULTI_TARGET = "MULTI_TARGET"
    UNKNOWN = "UNKNOWN"


class NetworkRule(FrozenContractModel):
    destination: NetworkDestinationClass
    requirement_id: SymbolicName | None = None
    endpoint_binding_id: SymbolicName | None = None
    transport: Literal["tcp", "udp"]
    ports: tuple[StrictInt, ...] = Field(
        min_length=1, json_schema_extra={"collection_semantics": "set"}
    )

    @model_validator(mode="after")
    def shape(self) -> Self:
        if any(not 1 <= port <= 65535 for port in self.ports):
            raise ValueError("network ports must be bounded endpoint ports")
        if self.destination is not NetworkDestinationClass.SELECTED_TARGET and (
            self.requirement_id is None and self.endpoint_binding_id is None
        ):
            raise ValueError(
                "non-target destinations require an explicit endpoint requirement/binding"
            )
        return self


class NetworkConstraints(FrozenContractModel):
    unspecified: Literal["DISALLOW"] = "DISALLOW"
    rules: tuple[NetworkRule, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )


class ExecutionLimits(FrozenContractModel):
    """Finite numeric intent; enforcement belongs to E/F, not this schema."""

    wall_time_seconds: StrictInt = Field(ge=1, le=86400)
    process_count: StrictInt = Field(ge=1, le=1024)
    memory_bytes: StrictInt = Field(ge=1, le=1099511627776)
    output_bytes: StrictInt = Field(ge=1, le=1099511627776)
    disk_write_bytes: StrictInt = Field(ge=0, le=1099511627776)


class ExpectedEvidence(FrozenContractModel):
    evidence_id: SymbolicName
    kind: Literal["STDOUT", "STDERR", "OUTPUT_FILE", "OBSERVATION"]
    semantic_type: SymbolicName
    relative_path: RelativeSourcePath | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if (self.kind == "OUTPUT_FILE") != (self.relative_path is not None):
            raise ValueError("only output-file evidence has a relative path")
        if self.relative_path is not None:
            validate_relative_path(self.relative_path)
        return self


class ExpectedResult(FrozenContractModel):
    """A proposed expectation, not an observed effect or target assessment."""

    semantic_type: SymbolicName
    evidence_ids: tuple[SymbolicName, ...] = Field(
        min_length=1, json_schema_extra={"collection_semantics": "set"}
    )
    scope: EffectScope
