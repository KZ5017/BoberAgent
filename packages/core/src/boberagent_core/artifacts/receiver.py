"""Core endpoint for durable, verified Artifact transfer messages."""

from __future__ import annotations

from boberagent_contracts import ArtifactRef
from boberagent_transport import (
    TRANSPORT_PROTOCOL_VERSION,
    ArtifactChunk,
    ArtifactTransferAcknowledgement,
    ArtifactTransferFinalize,
    ArtifactTransferReady,
    ArtifactTransferRejection,
    ArtifactTransferRequest,
    ArtifactTransferResponse,
    ArtifactTransferStart,
    ensure_supported_protocol,
    parse_artifact_request,
    serialize_message,
)

from boberagent_core.models import ArtifactContentState, StoredArtifact
from boberagent_core.persistence import CoreDatabase, PersistenceIntegrityError

from .storage import (
    ArtifactIntegrityError,
    ArtifactOffsetError,
    ArtifactStorageError,
    FilesystemArtifactStorage,
)


class CoreArtifactReceiver:
    """Receive chunks without exposing partial content through the Core API."""

    def __init__(self, database: CoreDatabase, storage: FilesystemArtifactStorage) -> None:
        self._database = database
        self._storage = storage

    async def accept_artifact_message(self, message: bytes) -> bytes:
        request = parse_artifact_request(message)
        ensure_supported_protocol(request.protocol_version)
        response = self._dispatch(request)
        return serialize_message(response)

    def _dispatch(self, request: ArtifactTransferRequest) -> ArtifactTransferResponse:
        if isinstance(request, ArtifactTransferStart):
            return self._start(request)
        if isinstance(request, ArtifactChunk):
            return self._chunk(request)
        return self._finalize(request)

    def _start(
        self, request: ArtifactTransferStart
    ) -> ArtifactTransferReady | ArtifactTransferAcknowledgement | ArtifactTransferRejection:
        descriptor = request.descriptor
        if descriptor.sha256 is None or descriptor.size_bytes is None:
            return self._reject(request, "METADATA_REQUIRED", "SHA-256 and size are required")
        if descriptor.size_bytes > self._storage.configuration.max_artifact_size_bytes:
            return self._reject(
                request,
                "ARTIFACT_TOO_LARGE",
                "Artifact exceeds the configured maximum size",
            )
        try:
            with self._database.unit_of_work() as work:
                record = work.artifacts.prepare_transfer(
                    descriptor,
                    source_node_id=request.node_id,
                    transfer_id=str(request.transfer_id),
                )
                content_key = work.artifacts.content_key(descriptor.artifact_id)
        except PersistenceIntegrityError as error:
            return self._reject(request, "ARTIFACT_IDENTITY_CONFLICT", str(error))

        if record.content_state is ArtifactContentState.AVAILABLE:
            if content_key is not None and self._storage.content_exists(content_key):
                return self._ack(request, record, deduplicated=True)
            with self._database.unit_of_work() as work:
                work.artifacts.fail_transfer(
                    descriptor.artifact_id, "catalog content is missing from managed storage"
                )
            return self._reject(
                request,
                "CONTENT_MISSING",
                "Artifact catalog content is missing",
                retryable=True,
            )

        offset = self._storage.reconcile_transfer(str(request.transfer_id), record.received_bytes)
        if offset != record.received_bytes:
            with self._database.unit_of_work() as work:
                work.artifacts.set_transfer_progress(descriptor.artifact_id, offset)
        return self._ready(request, offset)

    def _chunk(
        self, request: ArtifactChunk
    ) -> ArtifactTransferReady | ArtifactTransferAcknowledgement | ArtifactTransferRejection:
        record, rejection = self._active_record(request)
        if rejection is not None:
            return rejection
        assert record is not None
        descriptor = record.descriptor
        if record.content_state is ArtifactContentState.AVAILABLE:
            return self._ack(request, record, deduplicated=True)
        if descriptor.size_bytes is None:
            return self._reject(request, "METADATA_REQUIRED", "Artifact size is unavailable")
        try:
            next_offset = self._storage.append_chunk(
                str(request.transfer_id),
                offset=request.offset,
                data=request.data,
                durable_offset=record.received_bytes,
                declared_size=descriptor.size_bytes,
            )
        except ArtifactOffsetError as error:
            return self._reject(request, "INVALID_CHUNK_OFFSET", str(error), retryable=True)
        except ArtifactStorageError as error:
            return self._reject(request, "CHUNK_REJECTED", str(error))
        if next_offset != record.received_bytes:
            with self._database.unit_of_work() as work:
                work.artifacts.set_transfer_progress(request.artifact_ref, next_offset)
        return self._ready(request, next_offset)

    def _finalize(
        self, request: ArtifactTransferFinalize
    ) -> ArtifactTransferAcknowledgement | ArtifactTransferRejection:
        record, rejection = self._active_record(request)
        if rejection is not None:
            return rejection
        assert record is not None
        descriptor = record.descriptor
        if record.content_state is ArtifactContentState.AVAILABLE:
            return self._ack(request, record, deduplicated=True)
        if descriptor.sha256 is None or descriptor.size_bytes is None:
            return self._reject(request, "METADATA_REQUIRED", "SHA-256 and size are required")
        if record.received_bytes != descriptor.size_bytes:
            return self._reject(
                request,
                "TRANSFER_INCOMPLETE",
                "Artifact transfer is missing bytes",
                retryable=True,
            )
        try:
            self._storage.verify_temporary(
                str(request.transfer_id),
                digest=descriptor.sha256,
                size=descriptor.size_bytes,
            )
            content_key, deduplicated = self._storage.publish(
                str(request.transfer_id),
                digest=descriptor.sha256,
                size=descriptor.size_bytes,
            )
        except ArtifactIntegrityError as error:
            self._storage.discard_transfer(str(request.transfer_id))
            with self._database.unit_of_work() as work:
                work.artifacts.fail_transfer(request.artifact_ref, str(error))
            return self._reject(request, "INTEGRITY_MISMATCH", str(error))
        with self._database.unit_of_work() as work:
            completed = work.artifacts.complete_transfer(request.artifact_ref, content_key)
        return self._ack(request, completed, deduplicated=deduplicated)

    def _active_record(
        self, request: ArtifactChunk | ArtifactTransferFinalize
    ) -> tuple[StoredArtifact | None, ArtifactTransferRejection | None]:
        with self._database.unit_of_work() as work:
            record = work.artifacts.get_record(request.artifact_ref)
            identity = work.artifacts.transfer_identity(request.artifact_ref)
        if record is None:
            return None, self._reject(request, "TRANSFER_UNKNOWN", "Artifact transfer is unknown")
        if record.content_state not in {
            ArtifactContentState.RECEIVING,
            ArtifactContentState.AVAILABLE,
        }:
            return None, self._reject(
                request,
                "TRANSFER_NOT_ACTIVE",
                "Artifact transfer must be opened before chunks or finalization",
                retryable=True,
            )
        if identity != (
            request.node_id,
            str(request.transfer_id),
        ):
            return None, self._reject(
                request,
                "TRANSFER_IDENTITY_MISMATCH",
                "Artifact transfer identity does not match the active transfer",
            )
        return record, None

    def _ready(self, request: ArtifactTransferRequest, next_offset: int) -> ArtifactTransferReady:
        return ArtifactTransferReady(
            protocol_version=TRANSPORT_PROTOCOL_VERSION,
            request_message_id=request.message_id,
            node_id=request.node_id,
            transfer_id=request.transfer_id,
            artifact_ref=_artifact_ref(request),
            next_offset=next_offset,
        )

    def _ack(
        self,
        request: ArtifactTransferRequest,
        record: StoredArtifact,
        *,
        deduplicated: bool,
    ) -> ArtifactTransferAcknowledgement:
        descriptor = record.descriptor
        if descriptor.sha256 is None or descriptor.size_bytes is None:
            raise RuntimeError("completed Artifact lacks integrity metadata")
        return ArtifactTransferAcknowledgement(
            protocol_version=TRANSPORT_PROTOCOL_VERSION,
            request_message_id=request.message_id,
            node_id=request.node_id,
            transfer_id=request.transfer_id,
            artifact_ref=descriptor.artifact_id,
            sha256=descriptor.sha256,
            size_bytes=descriptor.size_bytes,
            deduplicated=deduplicated,
        )

    def _reject(
        self,
        request: ArtifactTransferRequest,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> ArtifactTransferRejection:
        return ArtifactTransferRejection(
            protocol_version=TRANSPORT_PROTOCOL_VERSION,
            request_message_id=request.message_id,
            node_id=request.node_id,
            transfer_id=request.transfer_id,
            artifact_ref=_artifact_ref(request),
            code=code,
            message=message,
            retryable=retryable,
        )


def _artifact_ref(request: ArtifactTransferRequest) -> ArtifactRef:
    if isinstance(request, ArtifactTransferStart):
        return request.descriptor.artifact_id
    return request.artifact_ref
