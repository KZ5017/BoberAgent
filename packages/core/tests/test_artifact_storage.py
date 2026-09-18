"""Chunked Core Artifact storage, integrity, retry, and confinement tests."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_contracts import (
    ArtifactDescriptor,
    ArtifactRef,
    CapabilityRunRef,
    JsonObject,
    StorageRef,
)
from boberagent_core import (
    ArtifactContentState,
    ArtifactStorageConfiguration,
    CoreArtifactReceiver,
    CoreArtifactService,
    CoreDatabase,
    DatabaseConfig,
    FilesystemArtifactStorage,
    upgrade_database,
)
from boberagent_transport import (
    ArtifactChunk,
    ArtifactTransferAcknowledgement,
    ArtifactTransferFinalize,
    ArtifactTransferReady,
    ArtifactTransferRejection,
    ArtifactTransferStart,
    InMemoryTransport,
    artifact_chunk_message_id,
    artifact_finalize_message_id,
    artifact_start_message_id,
    artifact_transfer_id,
)

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
NODE_ID = "node-artifact-core-test"


class ArtifactNodeEndpoint:
    @property
    def node_id(self) -> str:
        return NODE_ID

    async def handshake(self, request: bytes) -> bytes:
        return request

    async def accept_invocation(self, message: bytes) -> None:
        del message

    async def pending_outbound(self) -> tuple[bytes, ...]:
        return ()

    async def query_run_status(self, message: bytes) -> bytes:
        del message
        return b""

    async def acknowledge(self, message: bytes) -> None:
        del message


def _descriptor(
    artifact_id: str,
    data: bytes,
    *,
    declared_hash: str | None = None,
    declared_size: int | None = None,
    metadata: JsonObject | None = None,
) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        artifact_id=ArtifactRef(artifact_id),
        artifact_type="test.raw",
        storage_ref=StorageRef(f"node-spool:{artifact_id}"),
        created_by_run=CapabilityRunRef(f"run-{artifact_id}"),
        created_at=NOW,
        sha256=hashlib.sha256(data).hexdigest() if declared_hash is None else declared_hash,
        size_bytes=len(data) if declared_size is None else declared_size,
        media_type="application/octet-stream",
        metadata={} if metadata is None else metadata,
    )


def _components(
    tmp_path: Path,
    *,
    max_size: int = 16 * 1024**3,
) -> tuple[
    CoreDatabase,
    FilesystemArtifactStorage,
    CoreArtifactService,
    InMemoryTransport,
]:
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(database)
    storage = FilesystemArtifactStorage(
        ArtifactStorageConfiguration(
            root=tmp_path / "artifact-store",
            max_artifact_size_bytes=max_size,
            max_chunk_size_bytes=64,
        )
    )
    service = CoreArtifactService(database, storage)
    transport = InMemoryTransport()
    transport.register_node(ArtifactNodeEndpoint())
    transport.register_artifact_receiver(CoreArtifactReceiver(database, storage))
    return database, storage, service, transport


async def _transfer(
    transport: InMemoryTransport,
    descriptor: ArtifactDescriptor,
    data: bytes,
    *,
    chunk_size: int,
) -> tuple[ArtifactTransferAcknowledgement | ArtifactTransferRejection, int]:
    transfer_id = artifact_transfer_id(NODE_ID, descriptor.artifact_id)
    start = await transport.exchange_artifact(
        ArtifactTransferStart(
            message_id=artifact_start_message_id(transfer_id),
            node_id=NODE_ID,
            transfer_id=transfer_id,
            timestamp=NOW,
            descriptor=descriptor,
        )
    )
    if isinstance(start, (ArtifactTransferAcknowledgement, ArtifactTransferRejection)):
        return start, 0
    offset = start.next_offset
    chunks = 0
    while offset < len(data):
        content = data[offset : offset + chunk_size]
        response = await transport.exchange_artifact(
            ArtifactChunk(
                message_id=artifact_chunk_message_id(transfer_id, offset),
                node_id=NODE_ID,
                transfer_id=transfer_id,
                artifact_ref=descriptor.artifact_id,
                timestamp=NOW,
                offset=offset,
                data=content,
                chunk_sha256=hashlib.sha256(content).hexdigest(),
            )
        )
        chunks += 1
        if isinstance(response, ArtifactTransferRejection):
            return response, chunks
        assert isinstance(response, ArtifactTransferReady)
        offset = response.next_offset
    final = await transport.exchange_artifact(
        ArtifactTransferFinalize(
            message_id=artifact_finalize_message_id(transfer_id),
            node_id=NODE_ID,
            transfer_id=transfer_id,
            artifact_ref=descriptor.artifact_id,
            timestamp=NOW,
        )
    )
    assert not isinstance(final, ArtifactTransferReady)
    return final, chunks


@pytest.mark.parametrize(
    ("artifact_id", "data", "chunk_size", "minimum_chunks"),
    [
        ("artifact-text", b"small text", 64, 1),
        ("artifact-binary", b"\x00\xff\x10\x80binary\x00", 4, 3),
        ("artifact-empty", b"", 64, 0),
        ("artifact-multichunk", bytes(range(256)) * 4, 31, 30),
    ],
)
def test_artifact_content_round_trip_and_chunking(
    tmp_path: Path,
    artifact_id: str,
    data: bytes,
    chunk_size: int,
    minimum_chunks: int,
) -> None:
    database, _storage, service, transport = _components(tmp_path)
    descriptor = _descriptor(artifact_id, data)

    async def scenario() -> tuple[ArtifactTransferAcknowledgement, int]:
        await transport.connect()
        response, chunks = await _transfer(transport, descriptor, data, chunk_size=chunk_size)
        assert isinstance(response, ArtifactTransferAcknowledgement)
        await transport.disconnect()
        return response, chunks

    try:
        acknowledgement, chunks = asyncio.run(scenario())
        assert chunks >= minimum_chunks
        assert acknowledgement.artifact_ref == descriptor.artifact_id
        assert acknowledgement.sha256 == hashlib.sha256(data).hexdigest()
        record = service.get(descriptor.artifact_id)
        assert record is not None
        assert record.descriptor == descriptor
        assert record.content_state is ArtifactContentState.AVAILABLE
        assert service.read_bytes(descriptor.artifact_id) == data
    finally:
        database.dispose()


def test_identical_retry_and_conflicting_artifact_identity(tmp_path: Path) -> None:
    database, _storage, service, transport = _components(tmp_path)
    original = b"canonical content"
    descriptor = _descriptor("artifact-identity", original)

    async def scenario() -> tuple[object, object, object]:
        await transport.connect()
        first, _ = await _transfer(transport, descriptor, original, chunk_size=5)
        replay, _ = await _transfer(transport, descriptor, original, chunk_size=5)
        conflict_descriptor = _descriptor("artifact-identity", b"different content")
        conflict, _ = await _transfer(
            transport, conflict_descriptor, b"different content", chunk_size=5
        )
        await transport.disconnect()
        return first, replay, conflict

    try:
        first, replay, conflict = asyncio.run(scenario())
        assert isinstance(first, ArtifactTransferAcknowledgement)
        assert isinstance(replay, ArtifactTransferAcknowledgement)
        assert replay.deduplicated
        assert isinstance(conflict, ArtifactTransferRejection)
        assert conflict.code == "ARTIFACT_IDENTITY_CONFLICT"
        assert service.read_bytes(descriptor.artifact_id) == original
    finally:
        database.dispose()


def test_corrupt_hash_and_declared_size_are_not_exposed(tmp_path: Path) -> None:
    database, _storage, service, transport = _components(tmp_path)
    data = b"actual bytes"
    corrupt = _descriptor("artifact-corrupt", data, declared_hash="0" * 64)
    wrong_size = _descriptor("artifact-wrong-size", data, declared_size=3)

    async def scenario() -> tuple[object, object]:
        await transport.connect()
        hash_response, _ = await _transfer(transport, corrupt, data, chunk_size=64)
        size_response, _ = await _transfer(transport, wrong_size, data, chunk_size=64)
        await transport.disconnect()
        return hash_response, size_response

    try:
        hash_response, size_response = asyncio.run(scenario())
        assert isinstance(hash_response, ArtifactTransferRejection)
        assert hash_response.code == "INTEGRITY_MISMATCH"
        assert isinstance(size_response, ArtifactTransferRejection)
        assert size_response.code == "INVALID_CHUNK_OFFSET"
        for descriptor in (corrupt, wrong_size):
            assert not service.content_available(descriptor.artifact_id)
            with pytest.raises(FileNotFoundError):
                service.read_bytes(descriptor.artifact_id)
    finally:
        database.dispose()


def test_incomplete_transfer_restart_is_resumable_and_not_visible(tmp_path: Path) -> None:
    database, _storage, service, transport = _components(tmp_path)
    data = b"resume-this-content"
    descriptor = _descriptor("artifact-resume", data)
    transfer_id = artifact_transfer_id(NODE_ID, descriptor.artifact_id)

    async def partial() -> None:
        await transport.connect()
        start = await transport.exchange_artifact(
            ArtifactTransferStart(
                message_id=artifact_start_message_id(transfer_id),
                node_id=NODE_ID,
                transfer_id=transfer_id,
                timestamp=NOW,
                descriptor=descriptor,
            )
        )
        assert isinstance(start, ArtifactTransferReady)
        first = data[:7]
        progress = await transport.exchange_artifact(
            ArtifactChunk(
                message_id=artifact_chunk_message_id(transfer_id, 0),
                node_id=NODE_ID,
                transfer_id=transfer_id,
                artifact_ref=descriptor.artifact_id,
                timestamp=NOW,
                offset=0,
                data=first,
                chunk_sha256=hashlib.sha256(first).hexdigest(),
            )
        )
        assert isinstance(progress, ArtifactTransferReady)
        await transport.disconnect()

    asyncio.run(partial())
    assert not service.content_available(descriptor.artifact_id)
    database.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(reopened)
    storage = FilesystemArtifactStorage(
        ArtifactStorageConfiguration(root=tmp_path / "artifact-store", max_chunk_size_bytes=64)
    )
    restarted_service = CoreArtifactService(reopened, storage)
    restarted_transport = InMemoryTransport()
    restarted_transport.register_node(ArtifactNodeEndpoint())
    restarted_transport.register_artifact_receiver(CoreArtifactReceiver(reopened, storage))

    async def resume() -> ArtifactTransferAcknowledgement | ArtifactTransferRejection:
        await restarted_transport.connect()
        response, _ = await _transfer(restarted_transport, descriptor, data, chunk_size=5)
        await restarted_transport.disconnect()
        return response

    try:
        response = asyncio.run(resume())
        assert isinstance(response, ArtifactTransferAcknowledgement)
        assert restarted_service.read_bytes(descriptor.artifact_id) == data
    finally:
        reopened.dispose()


def test_untrusted_filename_metadata_never_controls_storage_path(tmp_path: Path) -> None:
    database, _storage, service, transport = _components(tmp_path)
    data = b"confined"
    descriptor = _descriptor(
        "artifact-confined",
        data,
        metadata={"filename": "../../escaped.bin", "absolute": "/tmp/escaped.bin"},
    )

    async def scenario() -> object:
        await transport.connect()
        response, _ = await _transfer(transport, descriptor, data, chunk_size=4)
        await transport.disconnect()
        return response

    try:
        assert isinstance(asyncio.run(scenario()), ArtifactTransferAcknowledgement)
        assert service.read_bytes(descriptor.artifact_id) == data
        assert not (tmp_path / "escaped.bin").exists()
        assert not (tmp_path / "artifact-store" / "escaped.bin").exists()
    finally:
        database.dispose()


def test_duplicate_conflicting_and_out_of_order_chunks_are_detected(tmp_path: Path) -> None:
    database, _storage, service, transport = _components(tmp_path)
    data = b"abcdefgh"
    descriptor = _descriptor("artifact-chunk-order", data)
    transfer_id = artifact_transfer_id(NODE_ID, descriptor.artifact_id)

    def chunk(offset: int, content: bytes) -> ArtifactChunk:
        return ArtifactChunk(
            message_id=artifact_chunk_message_id(transfer_id, offset),
            node_id=NODE_ID,
            transfer_id=transfer_id,
            artifact_ref=descriptor.artifact_id,
            timestamp=NOW,
            offset=offset,
            data=content,
            chunk_sha256=hashlib.sha256(content).hexdigest(),
        )

    async def scenario() -> tuple[object, object, object, object, object]:
        await transport.connect()
        start = await transport.exchange_artifact(
            ArtifactTransferStart(
                message_id=artifact_start_message_id(transfer_id),
                node_id=NODE_ID,
                transfer_id=transfer_id,
                timestamp=NOW,
                descriptor=descriptor,
            )
        )
        first = await transport.exchange_artifact(chunk(0, b"abcd"))
        duplicate = await transport.exchange_artifact(chunk(0, b"abcd"))
        conflict = await transport.exchange_artifact(chunk(0, b"wxyz"))
        gap = await transport.exchange_artifact(chunk(6, b"gh"))
        await transport.disconnect()
        return start, first, duplicate, conflict, gap

    try:
        start, first, duplicate, conflict, gap = asyncio.run(scenario())
        assert isinstance(start, ArtifactTransferReady)
        assert isinstance(first, ArtifactTransferReady)
        assert first.next_offset == 4
        assert isinstance(duplicate, ArtifactTransferReady)
        assert duplicate.next_offset == 4
        assert isinstance(conflict, ArtifactTransferRejection)
        assert conflict.code == "INVALID_CHUNK_OFFSET"
        assert isinstance(gap, ArtifactTransferRejection)
        assert gap.code == "INVALID_CHUNK_OFFSET"
        assert not service.content_available(descriptor.artifact_id)
    finally:
        database.dispose()


def test_declared_artifact_size_limit_is_enforced_before_storage(tmp_path: Path) -> None:
    database, _storage, service, transport = _components(tmp_path, max_size=3)
    data = b"four"
    descriptor = _descriptor("artifact-too-large", data)

    async def scenario() -> object:
        await transport.connect()
        response, _ = await _transfer(transport, descriptor, data, chunk_size=2)
        await transport.disconnect()
        return response

    try:
        response = asyncio.run(scenario())
        assert isinstance(response, ArtifactTransferRejection)
        assert response.code == "ARTIFACT_TOO_LARGE"
        assert service.get(descriptor.artifact_id) is None
    finally:
        database.dispose()
