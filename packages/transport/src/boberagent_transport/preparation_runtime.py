"""Unwired E5-A serialization boundary. No endpoint, dispatch or provider implementation."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from boberagent_contracts import (
    CapabilityRunRef,
    PreparationPermitRef,
    RuntimePreparationRef,
    Sha256Digest,
)
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_contracts.python_runtime import (
    PythonRuntimeAuthorityProjection,
    PythonRuntimeCurrentState,
    PythonRuntimeEvidence,
    PythonRuntimeFailure,
    RuntimeResourceRef,
    python_runtime_binding_digest,
    python_runtime_request_digest,
)
from boberagent_contracts.runtime_preparation import PreparationNodeId
from pydantic import AwareDatetime, Field, TypeAdapter, ValidationError, model_validator

from .errors import MalformedMessage
from .models import TransportMessageId, TransportModel

PYTHON_RUNTIME_PROTOCOL_VERSION: Literal["preparation-runtime-v1"] = "preparation-runtime-v1"


class RuntimePreparationOperation(StrEnum):
    CHECK_RUNTIME = "CHECK_RUNTIME"
    PREPARE_RUNTIME = "PREPARE_RUNTIME"
    RUNTIME_STATUS = "RUNTIME_STATUS"
    REVALIDATE_RUNTIME = "REVALIDATE_RUNTIME"
    RELEASE_RUNTIME = "RELEASE_RUNTIME"


class _OperationIdentity(TransportModel):
    protocol: Literal["preparation-runtime-v1"] = PYTHON_RUNTIME_PROTOCOL_VERSION
    request_sha256: Sha256Digest
    operation: RuntimePreparationOperation
    resource_ref: RuntimeResourceRef | None
    binding_sha256: Sha256Digest | None


class PythonRuntimeRequest(TransportModel):
    protocol_version: Literal["preparation-runtime-v1"] = PYTHON_RUNTIME_PROTOCOL_VERSION
    message_type: Literal["preparation.runtime.request"] = "preparation.runtime.request"
    message_id: TransportMessageId
    node_id: PreparationNodeId
    preparation_ref: RuntimePreparationRef
    permit_ref: PreparationPermitRef
    permit_sha256: Sha256Digest
    run_ref: CapabilityRunRef
    operation: RuntimePreparationOperation
    authority: PythonRuntimeAuthorityProjection
    resource_ref: RuntimeResourceRef | None = None
    binding_sha256: Sha256Digest | None = None
    timestamp: AwareDatetime

    @model_validator(mode="after")
    def matching_claims(self) -> Self:
        binding = self.authority.binding
        if (
            self.node_id != binding.spec.node_id
            or self.preparation_ref != binding.spec.preparation_ref
            or self.permit_ref != binding.permit_ref
            or self.permit_sha256 != binding.permit_sha256
            or self.run_ref != binding.run_ref
        ):
            raise ValueError("runtime envelope does not match preparation authority claims")
        resource_operation = self.operation in {
            RuntimePreparationOperation.RUNTIME_STATUS,
            RuntimePreparationOperation.REVALIDATE_RUNTIME,
            RuntimePreparationOperation.RELEASE_RUNTIME,
        }
        if resource_operation != (
            self.resource_ref is not None and self.binding_sha256 is not None
        ):
            raise ValueError(
                "Resource operation requires exact ResourceRef and sealed binding digest"
            )
        if not resource_operation and (
            self.resource_ref is not None or self.binding_sha256 is not None
        ):
            raise ValueError("check/prepare bind the request, not a caller-selected Resource")
        if self.message_id != runtime_message_id(
            self.authority, self.operation, self.resource_ref, self.binding_sha256
        ):
            raise ValueError("runtime message identity mismatch")
        return self


def runtime_message_id(
    authority: PythonRuntimeAuthorityProjection,
    operation: RuntimePreparationOperation,
    resource_ref: RuntimeResourceRef | None = None,
    binding_sha256: Sha256Digest | None = None,
) -> TransportMessageId:
    # Timestamp is delivery metadata, not semantic operation identity.
    digest = canonical_digest(
        _OperationIdentity(
            request_sha256=python_runtime_request_digest(authority.binding),
            operation=operation,
            resource_ref=resource_ref,
            binding_sha256=binding_sha256,
        )
    )
    return TransportMessageId(f"preparation-runtime:{digest}")


class PythonRuntimeResponseBase(TransportModel):
    protocol_version: Literal["preparation-runtime-v1"] = PYTHON_RUNTIME_PROTOCOL_VERSION
    request_message_id: TransportMessageId
    node_id: PreparationNodeId
    preparation_ref: RuntimePreparationRef
    permit_ref: PreparationPermitRef
    permit_sha256: Sha256Digest
    run_ref: CapabilityRunRef
    timestamp: AwareDatetime


class PythonRuntimeAccepted(PythonRuntimeResponseBase):
    """Acceptance/correlation only; preparation completion remains E6-owned."""

    message_type: Literal["preparation.runtime.accepted"] = "preparation.runtime.accepted"
    request_binding_sha256: Sha256Digest
    resource_ref: RuntimeResourceRef | None
    current: PythonRuntimeCurrentState | None
    evidence: PythonRuntimeEvidence | None

    @model_validator(mode="after")
    def consistent_resource(self) -> Self:
        if self.current is not None and self.resource_ref != self.current.resource_ref:
            raise ValueError("runtime status ResourceRef mismatch")
        if self.evidence is not None:
            binding = self.evidence.binding
            request = binding.request
            if (
                self.resource_ref != binding.resource_ref
                or self.request_binding_sha256 != python_runtime_request_digest(request)
                or self.node_id != request.spec.node_id
                or self.preparation_ref != request.spec.preparation_ref
                or self.permit_ref != request.permit_ref
                or self.permit_sha256 != request.permit_sha256
                or self.run_ref != request.run_ref
            ):
                raise ValueError("runtime evidence response binding mismatch")
            if (
                self.current is not None
                and self.current.binding_sha256 != python_runtime_binding_digest(binding)
            ):
                raise ValueError("runtime status sealed binding mismatch")
        return self


class PythonRuntimeRejected(PythonRuntimeResponseBase):
    message_type: Literal["preparation.runtime.rejected"] = "preparation.runtime.rejected"
    failure: PythonRuntimeFailure


type PythonRuntimeResponse = PythonRuntimeAccepted | PythonRuntimeRejected
_RESPONSE: TypeAdapter[PythonRuntimeResponse] = TypeAdapter(
    Annotated[PythonRuntimeResponse, Field(discriminator="message_type")]
)


def parse_python_runtime_request(data: bytes) -> PythonRuntimeRequest:
    try:
        return PythonRuntimeRequest.model_validate_json(data)
    except (ValidationError, ValueError, TypeError) as error:
        raise MalformedMessage("invalid Python runtime request") from error


def parse_python_runtime_response(data: bytes) -> PythonRuntimeResponse:
    try:
        return _RESPONSE.validate_json(data)
    except (ValidationError, ValueError, TypeError) as error:
        raise MalformedMessage("invalid Python runtime response") from error
