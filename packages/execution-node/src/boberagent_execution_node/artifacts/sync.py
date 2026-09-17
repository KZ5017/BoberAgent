"""Retry-safe Node coordinator for chunked Artifact synchronization."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from boberagent_contracts import ArtifactRef
from boberagent_contracts.artifact import ArtifactDescriptor
from boberagent_transport import (
    MAX_PROTOCOL_CHUNK_BYTES,
    ArtifactChunk,
    ArtifactTransferAcknowledgement,
    ArtifactTransferFinalize,
    ArtifactTransferReady,
    ArtifactTransferRejection,
    ArtifactTransferStart,
    ArtifactTransport,
    artifact_chunk_message_id,
    artifact_finalize_message_id,
    artifact_start_message_id,
    artifact_transfer_id,
)
from pydantic import BaseModel, ConfigDict, Field

from boberagent_execution_node.persistence import RuntimeStore


class ArtifactSyncOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_ref: ArtifactRef
    synchronized: bool
    code: str
    message: str
    chunks_sent: int = Field(ge=0)
    bytes_sent: int = Field(ge=0)


class ArtifactSyncCoordinator:
    def __init__(
        self,
        *,
        store: RuntimeStore,
        spool_root: Path,
        node_id: str,
        transport: ArtifactTransport,
        clock: Callable[[], datetime],
        chunk_size: int = 256 * 1024,
    ) -> None:
        if chunk_size < 1 or chunk_size > MAX_PROTOCOL_CHUNK_BYTES:
            raise ValueError(f"chunk_size must be between 1 and {MAX_PROTOCOL_CHUNK_BYTES} bytes")
        self._store = store
        self._spool_root = spool_root.resolve()
        self._node_id = node_id
        self._transport = transport
        self._clock = clock
        self._chunk_size = chunk_size

    async def synchronize_pending(self) -> tuple[ArtifactSyncOutcome, ...]:
        outcomes: list[ArtifactSyncOutcome] = []
        for record in self._store.list_artifacts_for_sync():
            outcomes.append(await self.synchronize(record.descriptor.artifact_id))
        return tuple(outcomes)

    async def synchronize(self, artifact_ref: ArtifactRef) -> ArtifactSyncOutcome:
        self._store.begin_artifact_sync(artifact_ref, self._clock())
        record = self._store.get_artifact(artifact_ref)
        if record is None:
            raise KeyError(f"unknown local Artifact: {artifact_ref}")
        descriptor = record.descriptor
        transfer_id = artifact_transfer_id(self._node_id, artifact_ref)
        chunks_sent = 0
        bytes_sent = 0
        try:
            path = Path(record.local_path).resolve(strict=True)
            if not path.is_file() or not path.is_relative_to(self._spool_root):
                raise ValueError("local Artifact path escapes the configured spool root")
            response = await self._transport.exchange_artifact(
                ArtifactTransferStart(
                    message_id=artifact_start_message_id(transfer_id),
                    node_id=self._node_id,
                    transfer_id=transfer_id,
                    timestamp=self._clock(),
                    descriptor=descriptor,
                )
            )
            if isinstance(response, ArtifactTransferRejection):
                return self._failed(artifact_ref, response.code, response.message)
            if isinstance(response, ArtifactTransferAcknowledgement):
                self._validate_acknowledgement(response, descriptor)
                return self._completed(artifact_ref, chunks_sent, bytes_sent, deduplicated=True)

            next_offset = response.next_offset
            file_size = path.stat().st_size
            if next_offset > file_size:
                raise ValueError("Core requested an offset beyond the local Artifact")
            with path.open("rb") as stream:
                stream.seek(next_offset)
                while data := stream.read(self._chunk_size):
                    request = ArtifactChunk(
                        message_id=artifact_chunk_message_id(transfer_id, next_offset),
                        node_id=self._node_id,
                        transfer_id=transfer_id,
                        artifact_ref=artifact_ref,
                        timestamp=self._clock(),
                        offset=next_offset,
                        data=data,
                        chunk_sha256=hashlib.sha256(data).hexdigest(),
                    )
                    response = await self._transport.exchange_artifact(request)
                    chunks_sent += 1
                    bytes_sent += len(data)
                    if isinstance(response, ArtifactTransferRejection):
                        return self._failed(artifact_ref, response.code, response.message)
                    if isinstance(response, ArtifactTransferAcknowledgement):
                        self._validate_acknowledgement(response, descriptor)
                        return self._completed(
                            artifact_ref, chunks_sent, bytes_sent, deduplicated=True
                        )
                    if not isinstance(response, ArtifactTransferReady):
                        raise ValueError("unexpected Artifact chunk response")
                    if response.next_offset < next_offset + len(data):
                        raise ValueError("Core did not durably accept the complete Artifact chunk")
                    next_offset = response.next_offset
                    stream.seek(next_offset)

            response = await self._transport.exchange_artifact(
                ArtifactTransferFinalize(
                    message_id=artifact_finalize_message_id(transfer_id),
                    node_id=self._node_id,
                    transfer_id=transfer_id,
                    artifact_ref=artifact_ref,
                    timestamp=self._clock(),
                )
            )
            if isinstance(response, ArtifactTransferAcknowledgement):
                self._validate_acknowledgement(response, descriptor)
                return self._completed(
                    artifact_ref,
                    chunks_sent,
                    bytes_sent,
                    deduplicated=response.deduplicated,
                )
            if isinstance(response, ArtifactTransferRejection):
                return self._failed(artifact_ref, response.code, response.message)
            raise ValueError("Core did not finalize the Artifact transfer")
        except Exception as error:
            return self._failed(
                artifact_ref,
                type(error).__name__.upper(),
                str(error) or "Artifact synchronization failed",
            )

    def _completed(
        self,
        artifact_ref: ArtifactRef,
        chunks_sent: int,
        bytes_sent: int,
        *,
        deduplicated: bool,
    ) -> ArtifactSyncOutcome:
        self._store.complete_artifact_sync(artifact_ref)
        return ArtifactSyncOutcome(
            artifact_ref=artifact_ref,
            synchronized=True,
            code="ALREADY_SYNCHRONIZED" if deduplicated else "SYNCHRONIZED",
            message="Artifact content is durably available in Core",
            chunks_sent=chunks_sent,
            bytes_sent=bytes_sent,
        )

    @staticmethod
    def _validate_acknowledgement(
        acknowledgement: ArtifactTransferAcknowledgement,
        descriptor: ArtifactDescriptor,
    ) -> None:
        if (
            descriptor.sha256 is None
            or descriptor.size_bytes is None
            or acknowledgement.sha256 != descriptor.sha256
            or acknowledgement.size_bytes != descriptor.size_bytes
        ):
            raise ValueError(
                "Core acknowledgement does not match local Artifact integrity metadata"
            )

    def _failed(self, artifact_ref: ArtifactRef, code: str, message: str) -> ArtifactSyncOutcome:
        diagnostic = f"{code}: {message}"
        self._store.fail_artifact_sync(artifact_ref, diagnostic)
        return ArtifactSyncOutcome(
            artifact_ref=artifact_ref,
            synchronized=False,
            code=code,
            message=message,
            chunks_sent=0,
            bytes_sent=0,
        )
