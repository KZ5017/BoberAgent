"""Transport-neutral, bounded Artifact transfer protocol messages."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal, Self

from boberagent_contracts import ArtifactDescriptor, ArtifactRef, DomainRef, Sha256Digest
from pydantic import AwareDatetime, Field, TypeAdapter, ValidationError, model_validator

from .errors import MalformedMessage
from .models import (
    TRANSPORT_PROTOCOL_VERSION,
    NodeIdentifier,
    TransportMessageId,
    TransportModel,
)

MAX_PROTOCOL_CHUNK_BYTES = 1024 * 1024


class ArtifactTransferId(DomainRef):
    """Stable identity for synchronizing one Artifact from one Node."""


class ArtifactTransferStart(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["artifact.transfer.start"] = "artifact.transfer.start"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    transfer_id: ArtifactTransferId
    timestamp: AwareDatetime
    descriptor: ArtifactDescriptor

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected_transfer = artifact_transfer_id(self.node_id, self.descriptor.artifact_id)
        if self.transfer_id != expected_transfer:
            raise ValueError("Artifact transfer identity is not stable")
        if self.message_id != artifact_start_message_id(self.transfer_id):
            raise ValueError("Artifact start message identity is not stable")
        if self.descriptor.sha256 is None or self.descriptor.size_bytes is None:
            raise ValueError("Artifact transfer requires declared SHA-256 and size")
        return self


class ArtifactChunk(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["artifact.transfer.chunk"] = "artifact.transfer.chunk"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    transfer_id: ArtifactTransferId
    artifact_ref: ArtifactRef
    timestamp: AwareDatetime
    offset: int = Field(ge=0)
    data: bytes = Field(min_length=1, max_length=MAX_PROTOCOL_CHUNK_BYTES)
    chunk_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_identity_and_hash(self) -> Self:
        if self.transfer_id != artifact_transfer_id(self.node_id, self.artifact_ref):
            raise ValueError("Artifact chunk transfer identity is not stable")
        if self.message_id != artifact_chunk_message_id(self.transfer_id, self.offset):
            raise ValueError("Artifact chunk message identity is not stable")
        if hashlib.sha256(self.data).hexdigest() != self.chunk_sha256:
            raise ValueError("Artifact chunk SHA-256 does not match its bytes")
        return self


class ArtifactTransferFinalize(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["artifact.transfer.finalize"] = "artifact.transfer.finalize"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    transfer_id: ArtifactTransferId
    artifact_ref: ArtifactRef
    timestamp: AwareDatetime

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.transfer_id != artifact_transfer_id(self.node_id, self.artifact_ref):
            raise ValueError("Artifact finalize transfer identity is not stable")
        if self.message_id != artifact_finalize_message_id(self.transfer_id):
            raise ValueError("Artifact finalize message identity is not stable")
        return self


type ArtifactTransferRequest = Annotated[
    ArtifactTransferStart | ArtifactChunk | ArtifactTransferFinalize,
    Field(discriminator="message_type"),
]


class ArtifactTransferReady(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["artifact.transfer.ready"] = "artifact.transfer.ready"
    request_message_id: TransportMessageId
    node_id: NodeIdentifier
    transfer_id: ArtifactTransferId
    artifact_ref: ArtifactRef
    next_offset: int = Field(ge=0)


class ArtifactTransferAcknowledgement(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["artifact.transfer.acknowledgement"] = "artifact.transfer.acknowledgement"
    request_message_id: TransportMessageId
    node_id: NodeIdentifier
    transfer_id: ArtifactTransferId
    artifact_ref: ArtifactRef
    sha256: Sha256Digest
    size_bytes: int = Field(ge=0)
    deduplicated: bool = False


class ArtifactTransferRejection(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["artifact.transfer.rejection"] = "artifact.transfer.rejection"
    request_message_id: TransportMessageId
    node_id: NodeIdentifier
    transfer_id: ArtifactTransferId
    artifact_ref: ArtifactRef
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1024)
    retryable: bool


type ArtifactTransferResponse = Annotated[
    ArtifactTransferReady | ArtifactTransferAcknowledgement | ArtifactTransferRejection,
    Field(discriminator="message_type"),
]

_request_adapter: TypeAdapter[ArtifactTransferRequest] = TypeAdapter(ArtifactTransferRequest)
_response_adapter: TypeAdapter[ArtifactTransferResponse] = TypeAdapter(ArtifactTransferResponse)


def artifact_transfer_id(node_id: str, artifact_ref: ArtifactRef) -> ArtifactTransferId:
    digest = _digest(node_id, str(artifact_ref))
    return ArtifactTransferId(f"artifact-transfer:{digest}")


def artifact_start_message_id(transfer_id: ArtifactTransferId) -> TransportMessageId:
    return _message_id("artifact-start", str(transfer_id))


def artifact_chunk_message_id(transfer_id: ArtifactTransferId, offset: int) -> TransportMessageId:
    return _message_id("artifact-chunk", str(transfer_id), str(offset))


def artifact_finalize_message_id(transfer_id: ArtifactTransferId) -> TransportMessageId:
    return _message_id("artifact-finalize", str(transfer_id))


def parse_artifact_request(data: bytes) -> ArtifactTransferRequest:
    try:
        return _request_adapter.validate_json(data)
    except (ValidationError, ValueError, TypeError) as error:
        raise MalformedMessage("invalid Artifact transfer request") from error


def parse_artifact_response(data: bytes) -> ArtifactTransferResponse:
    try:
        return _response_adapter.validate_json(data)
    except (ValidationError, ValueError, TypeError) as error:
        raise MalformedMessage("invalid Artifact transfer response") from error


def _message_id(prefix: str, *parts: str) -> TransportMessageId:
    return TransportMessageId(f"{prefix}:{_digest(*parts)}")


def _digest(*parts: str) -> str:
    value = "\0".join(parts).encode("utf-8")
    return hashlib.sha256(value).hexdigest()
