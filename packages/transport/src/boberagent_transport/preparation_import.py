"""Versioned, bounded Core-to-Node import of permit-pinned Artifact bytes.

These envelopes carry no filesystem path and are not a source repository. The
authenticated transport principal is deliberately *not* a serialized field.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal, Self

from boberagent_contracts import (
    ArtifactRef,
    CapabilityRunRef,
    DomainRef,
    PreparationPermitRef,
    RuntimePreparationRef,
    Sha256Digest,
)
from pydantic import AwareDatetime, Field, TypeAdapter, ValidationError, model_validator

from .errors import MalformedMessage
from .models import NodeIdentifier, TransportMessageId, TransportModel

PREPARATION_IMPORT_PROTOCOL_VERSION: Literal["preparation-import-v1"] = "preparation-import-v1"
MAX_IMPORT_CHUNK_BYTES = 1024 * 1024


class PreparationImportId(DomainRef):
    """Stable transfer identity scoped to one permit and one exact Artifact."""


class ImportStart(TransportModel):
    protocol_version: Literal["preparation-import-v1"] = PREPARATION_IMPORT_PROTOCOL_VERSION
    message_type: Literal["preparation.import.start"] = "preparation.import.start"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    preparation_ref: RuntimePreparationRef
    permit_ref: PreparationPermitRef
    run_ref: CapabilityRunRef
    import_id: PreparationImportId
    artifact_ref: ArtifactRef
    sha256: Sha256Digest
    size_bytes: int = Field(ge=0)
    timestamp: AwareDatetime

    @model_validator(mode="after")
    def stable_identity(self) -> Self:
        if self.import_id != preparation_import_id(self.permit_ref, self.artifact_ref):
            raise ValueError("preparation import identity mismatch")
        if self.message_id != import_message_id(self.import_id, "start"):
            raise ValueError("preparation import start message identity mismatch")
        return self


class ImportStatus(TransportModel):
    protocol_version: Literal["preparation-import-v1"] = PREPARATION_IMPORT_PROTOCOL_VERSION
    message_type: Literal["preparation.import.status"] = "preparation.import.status"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    preparation_ref: RuntimePreparationRef
    permit_ref: PreparationPermitRef
    run_ref: CapabilityRunRef
    import_id: PreparationImportId
    artifact_ref: ArtifactRef
    timestamp: AwareDatetime

    @model_validator(mode="after")
    def stable_identity(self) -> Self:
        if self.import_id != preparation_import_id(self.permit_ref, self.artifact_ref):
            raise ValueError("preparation import identity mismatch")
        if self.message_id != import_message_id(self.import_id, "status"):
            raise ValueError("preparation import status message identity mismatch")
        return self


class ImportChunk(TransportModel):
    protocol_version: Literal["preparation-import-v1"] = PREPARATION_IMPORT_PROTOCOL_VERSION
    message_type: Literal["preparation.import.chunk"] = "preparation.import.chunk"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    preparation_ref: RuntimePreparationRef
    permit_ref: PreparationPermitRef
    run_ref: CapabilityRunRef
    import_id: PreparationImportId
    artifact_ref: ArtifactRef
    offset: int = Field(ge=0)
    data: bytes = Field(min_length=1, max_length=MAX_IMPORT_CHUNK_BYTES)
    chunk_sha256: Sha256Digest
    timestamp: AwareDatetime

    @model_validator(mode="after")
    def stable_identity(self) -> Self:
        if self.import_id != preparation_import_id(self.permit_ref, self.artifact_ref):
            raise ValueError("preparation import identity mismatch")
        if self.message_id != import_message_id(self.import_id, f"chunk:{self.offset}"):
            raise ValueError("preparation import chunk message identity mismatch")
        if hashlib.sha256(self.data).hexdigest() != self.chunk_sha256:
            raise ValueError("preparation import chunk digest mismatch")
        return self


class ImportFinalize(TransportModel):
    protocol_version: Literal["preparation-import-v1"] = PREPARATION_IMPORT_PROTOCOL_VERSION
    message_type: Literal["preparation.import.finalize"] = "preparation.import.finalize"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    preparation_ref: RuntimePreparationRef
    permit_ref: PreparationPermitRef
    run_ref: CapabilityRunRef
    import_id: PreparationImportId
    artifact_ref: ArtifactRef
    timestamp: AwareDatetime

    @model_validator(mode="after")
    def stable_identity(self) -> Self:
        if self.import_id != preparation_import_id(self.permit_ref, self.artifact_ref):
            raise ValueError("preparation import identity mismatch")
        if self.message_id != import_message_id(self.import_id, "finalize"):
            raise ValueError("preparation import finalize message identity mismatch")
        return self


type ImportRequest = Annotated[
    ImportStart | ImportStatus | ImportChunk | ImportFinalize,
    Field(discriminator="message_type"),
]


class ImportReady(TransportModel):
    protocol_version: Literal["preparation-import-v1"] = PREPARATION_IMPORT_PROTOCOL_VERSION
    message_type: Literal["preparation.import.ready"] = "preparation.import.ready"
    request_message_id: TransportMessageId
    node_id: NodeIdentifier
    import_id: PreparationImportId
    artifact_ref: ArtifactRef
    next_offset: int = Field(ge=0)


class ImportCompleted(TransportModel):
    protocol_version: Literal["preparation-import-v1"] = PREPARATION_IMPORT_PROTOCOL_VERSION
    message_type: Literal["preparation.import.completed"] = "preparation.import.completed"
    request_message_id: TransportMessageId
    node_id: NodeIdentifier
    import_id: PreparationImportId
    artifact_ref: ArtifactRef
    sha256: Sha256Digest
    size_bytes: int = Field(ge=0)
    deduplicated: bool = False


class ImportRejected(TransportModel):
    protocol_version: Literal["preparation-import-v1"] = PREPARATION_IMPORT_PROTOCOL_VERSION
    message_type: Literal["preparation.import.rejected"] = "preparation.import.rejected"
    request_message_id: TransportMessageId
    node_id: NodeIdentifier
    import_id: PreparationImportId
    artifact_ref: ArtifactRef
    code: str = Field(min_length=1, max_length=128)
    retryable: bool


type ImportResponse = Annotated[
    ImportReady | ImportCompleted | ImportRejected,
    Field(discriminator="message_type"),
]

_requests: TypeAdapter[ImportRequest] = TypeAdapter(ImportRequest)
_responses: TypeAdapter[ImportResponse] = TypeAdapter(ImportResponse)


def preparation_import_id(
    permit_ref: PreparationPermitRef, artifact_ref: ArtifactRef
) -> PreparationImportId:
    value = hashlib.sha256(f"{permit_ref}\0{artifact_ref}".encode()).hexdigest()
    return PreparationImportId(f"preparation-import:{value}")


def import_message_id(import_id: PreparationImportId, action: str) -> TransportMessageId:
    value = hashlib.sha256(f"{import_id}\0{action}".encode()).hexdigest()
    return TransportMessageId(f"preparation-import-message:{value}")


def parse_import_request(data: bytes) -> ImportRequest:
    try:
        return _requests.validate_json(data)
    except (ValidationError, ValueError, TypeError) as error:
        raise MalformedMessage("invalid preparation import request") from error


def parse_import_response(data: bytes) -> ImportResponse:
    try:
        return _responses.validate_json(data)
    except (ValidationError, ValueError, TypeError) as error:
        raise MalformedMessage("invalid preparation import response") from error
