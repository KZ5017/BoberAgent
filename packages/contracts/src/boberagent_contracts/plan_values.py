"""Immutable, provider-neutral plan values. No resolution or runtime behavior."""

from enum import StrEnum
from ipaddress import ip_address
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StringConstraints, model_validator

from ._base import FrozenContractModel, NonEmptyStr, SymbolicName
from .artifact import Sha256Digest
from .refs import ArtifactRef, AssetRef, CredentialRef, SecretRef, ServiceRef

type RelativeSourcePath = Annotated[
    str, StringConstraints(min_length=1, max_length=1024, pattern=r"^[^\\\x00-\x1f:]+$")
]


def validate_relative_path(value: str) -> str:
    """Lexical validation only; never opens or resolves a filesystem path."""
    if value.startswith("/") or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("path must be normalized and source-relative")
    return value


class TargetRole(StrEnum):
    HOST = "HOST"
    IP = "IP"
    URL = "URL"
    SERVICE_ENDPOINT = "SERVICE_ENDPOINT"
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"
    REPOSITORY = "REPOSITORY"
    UNKNOWN = "UNKNOWN"


class NetworkTarget(FrozenContractModel):
    role: Literal[TargetRole.HOST, TargetRole.IP, TargetRole.URL, TargetRole.SERVICE_ENDPOINT]
    asset_ref: AssetRef
    service_ref: ServiceRef | None = None
    address: NonEmptyStr
    port: StrictInt | None = Field(default=None, ge=1, le=65535)
    transport: Literal["tcp", "udp"] | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if self.role is TargetRole.IP:
            ip_address(self.address)
        elif self.role is TargetRole.URL:
            url = urlsplit(self.address)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username
                or url.password
            ):
                raise ValueError(
                    "URL target needs an explicit HTTP(S) endpoint without credentials"
                )
        elif any(char.isspace() for char in self.address) or any(
            char in self.address for char in "/\\@"
        ):
            raise ValueError("host/endpoint address is not a file, URL or credential")
        if self.role is TargetRole.SERVICE_ENDPOINT:
            if self.port is None or self.transport is None:
                raise ValueError("service endpoint requires transport and port")
        elif self.port is not None or self.transport is not None or self.service_ref is not None:
            raise ValueError("service fields require SERVICE_ENDPOINT")
        return self


class SourceTarget(FrozenContractModel):
    role: Literal[TargetRole.FILE, TargetRole.DIRECTORY, TargetRole.REPOSITORY]
    artifact_ref: ArtifactRef
    relative_path: RelativeSourcePath | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        if self.role in (TargetRole.FILE, TargetRole.DIRECTORY) and self.relative_path is None:
            raise ValueError("file/directory target requires a relative path")
        if self.relative_path is not None:
            validate_relative_path(self.relative_path)
        return self


class UnknownTarget(FrozenContractModel):
    role: Literal[TargetRole.UNKNOWN] = TargetRole.UNKNOWN
    requirement_id: SymbolicName


type PlanTarget = Annotated[
    NetworkTarget | SourceTarget | UnknownTarget, Field(discriminator="role")
]


class ValueType(StrEnum):
    TEXT = "TEXT"
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    TARGET = "TARGET"
    PATH = "PATH"
    SECRET = "SECRET"
    CREDENTIAL = "CREDENTIAL"


class DeliveryChannel(StrEnum):
    ARGUMENT = "ARGUMENT"
    ENVIRONMENT = "ENVIRONMENT"
    STANDARD_INPUT = "STANDARD_INPUT"


class ResolutionState(StrEnum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


class BindingProvenance(FrozenContractModel):
    """Evidence identity or operator input; never an assertion of OBSERVED source truth."""

    origin: Literal["MISSION", "SOURCE_EVIDENCE", "OPERATOR", "PLANNING"]
    evidence_ids: tuple[SymbolicName, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    answer_id: SymbolicName | None = None


class MissionTargetValue(FrozenContractModel):
    source: Literal["mission_target"] = "mission_target"
    target_role: TargetRole


class LiteralValue(FrozenContractModel):
    source: Literal["literal"] = "literal"
    value: str | StrictInt | StrictFloat | StrictBool


class OperatorValue(FrozenContractModel):
    source: Literal["operator"] = "operator"
    answer_id: SymbolicName
    value: str | StrictInt | StrictFloat | StrictBool


class SecretValue(FrozenContractModel):
    source: Literal["secret_ref"] = "secret_ref"
    secret_ref: SecretRef


class CredentialValue(FrozenContractModel):
    source: Literal["credential_ref"] = "credential_ref"
    credential_ref: CredentialRef
    secret_role: SymbolicName


class CallbackValue(FrozenContractModel):
    source: Literal["callback_requirement"] = "callback_requirement"
    requirement_id: SymbolicName
    component: Literal["host", "port"]


class SourcePathValue(FrozenContractModel):
    source: Literal["source_path"] = "source_path"
    artifact_ref: ArtifactRef
    relative_path: RelativeSourcePath

    @model_validator(mode="after")
    def shape(self) -> Self:
        validate_relative_path(self.relative_path)
        return self


class ManagedPathValue(FrozenContractModel):
    source: Literal["managed_runtime_path"] = "managed_runtime_path"
    requirement_id: SymbolicName
    relative_path: RelativeSourcePath

    @model_validator(mode="after")
    def shape(self) -> Self:
        validate_relative_path(self.relative_path)
        return self


type BindingValue = Annotated[
    MissionTargetValue
    | LiteralValue
    | OperatorValue
    | SecretValue
    | CredentialValue
    | CallbackValue
    | SourcePathValue
    | ManagedPathValue,
    Field(discriminator="source"),
]


class ParameterBinding(FrozenContractModel):
    binding_id: SymbolicName
    parameter_id: SymbolicName
    value_type: ValueType
    channel: DeliveryChannel
    required: StrictBool
    resolution: ResolutionState
    value: BindingValue | None = None
    provenance: BindingProvenance

    @model_validator(mode="after")
    def shape(self) -> Self:
        if (self.resolution is ResolutionState.RESOLVED) != (self.value is not None):
            raise ValueError(
                "resolved bindings require a value; unresolved bindings cannot have one"
            )
        if self.value is None:
            return self
        expected = (
            ValueType.SECRET
            if isinstance(self.value, SecretValue)
            else ValueType.CREDENTIAL
            if isinstance(self.value, CredentialValue)
            else ValueType.TARGET
            if isinstance(self.value, MissionTargetValue)
            else ValueType.PATH
            if isinstance(self.value, SourcePathValue | ManagedPathValue)
            else None
        )
        if isinstance(self.value, CallbackValue):
            expected = ValueType.INTEGER if self.value.component == "port" else ValueType.TEXT
        if expected is not None and self.value_type is not expected:
            raise ValueError("binding source and value type disagree")
        if isinstance(self.value, LiteralValue | OperatorValue):
            scalar = self.value.value
            expected = (
                ValueType.BOOLEAN
                if isinstance(scalar, bool)
                else ValueType.INTEGER
                if isinstance(scalar, int)
                else ValueType.NUMBER
                if isinstance(scalar, float)
                else ValueType.TEXT
            )
            if self.value_type is not expected:
                raise ValueError(
                    "literal/operator scalar cannot substitute for a target/path/secret ref"
                )
        return self


class OptionToken(FrozenContractModel):
    kind: Literal["option"] = "option"
    name: Annotated[str, StringConstraints(pattern=r"^--?[A-Za-z][A-Za-z0-9_-]*$")]


class FlagToken(FrozenContractModel):
    kind: Literal["flag"] = "flag"
    name: Annotated[str, StringConstraints(pattern=r"^--?[A-Za-z][A-Za-z0-9_-]*$")]


class OptionValueToken(FrozenContractModel):
    kind: Literal["option_value"] = "option_value"
    name: Annotated[str, StringConstraints(pattern=r"^--?[A-Za-z][A-Za-z0-9_-]*$")]
    binding_id: SymbolicName
    style: Literal["separate", "equals"] = "separate"


class PositionalToken(FrozenContractModel):
    kind: Literal["positional"] = "positional"
    binding_id: SymbolicName


class BindingToken(FrozenContractModel):
    kind: Literal["binding"] = "binding"
    binding_id: SymbolicName


type ArgumentToken = Annotated[
    OptionToken | FlagToken | OptionValueToken | PositionalToken | BindingToken,
    Field(discriminator="kind"),
]


class InvocationLayout(FrozenContractModel):
    """Reviewed ordered layout, not a shell command or observed source fact."""

    origin: Literal["OPERATOR_REVIEWED"] = "OPERATOR_REVIEWED"
    review_id: SymbolicName
    evidence_ids: tuple[SymbolicName, ...] = Field(
        default=(), json_schema_extra={"collection_semantics": "set"}
    )
    arguments: tuple[ArgumentToken, ...]


class EnvironmentBinding(FrozenContractModel):
    name: Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
    binding_id: SymbolicName


class EntrypointIntent(FrozenContractModel):
    relative_path: RelativeSourcePath
    entry_sha256: Sha256Digest
    language: SymbolicName
    invocation_form: Literal["SCRIPT", "MODULE"]
    evidence_ids: tuple[SymbolicName, ...] = Field(
        min_length=1, json_schema_extra={"collection_semantics": "set"}
    )

    @model_validator(mode="after")
    def shape(self) -> Self:
        validate_relative_path(self.relative_path)
        return self
