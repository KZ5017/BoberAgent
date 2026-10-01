"""E3 trusted Node admission and opaque import fail-closed boundaries."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid5

import pytest
from boberagent_contracts import (
    ArtifactRef,
    CapabilityInvocation,
    CapabilityRunRef,
    PreparationPermit,
    RuntimePreparationInput,
    RuntimePreparationRef,
)
from boberagent_core.capabilities.models import provider_id_for
from boberagent_core.preparation import CoreRuntimePreparationAdmissionService
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_execution_node.preparation import PreparationAdmissionError
from boberagent_execution_node.preparation.service import _PROVIDER_NAMESPACE
from boberagent_transport import (
    ImportChunk,
    ImportCompleted,
    ImportFinalize,
    ImportReady,
    ImportRejected,
    ImportRequest,
    ImportResponse,
    ImportStart,
    ImportStatus,
    InvocationDelivery,
    InvocationEnvelope,
    MissionProjection,
    ProtocolError,
    import_message_id,
    invocation_message_id,
    preparation_import_id,
    serialize_message,
)
from test_runtime_preparation_e2 import NODE, _setup


def test_node_and_core_agree_on_stable_preparation_provider_identity() -> None:
    assert provider_id_for(NODE, "runtime.prepare") == uuid5(
        _PROVIDER_NAMESPACE, f"{NODE}\0runtime.prepare"
    )


def _envelope(permit: PreparationPermit) -> InvocationEnvelope:
    invocation = CapabilityInvocation(
        run_id=permit.run_ref,
        capability_id="runtime.prepare",
        operation="prepare",
        mission_ref=permit.spec.mission_ref,
        inputs=RuntimePreparationInput(
            schema_version="runtime-preparation-input-v1", permit=permit
        ).model_dump(mode="json"),
    )
    return InvocationEnvelope(
        message_id=invocation_message_id(permit.run_ref),
        node_id=NODE,
        correlation_id=permit.run_ref,
        timestamp=datetime.now(UTC),
        delivery=InvocationDelivery(
            invocation=invocation,
            mission=MissionProjection(mission_ref=permit.spec.mission_ref),
        ),
    )


def test_admission_rejects_untrusted_peer_and_mismatched_invocation(tmp_path: Path) -> None:
    database, _plan, policy, approvals, registry, _old, request = _setup(tmp_path)
    permit = (
        CoreRuntimePreparationAdmissionService(
            database, policy, approvals, registry, clock=lambda: datetime.now(UTC)
        )
        .admit(request)
        .permit
    )
    assert permit is not None

    async def scenario() -> None:
        node = ExecutionNode(
            NodeConfiguration.for_runtime_directory(tmp_path / "node", configured_node_id=NODE)
        )
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        envelope = _envelope(permit)
        try:
            with pytest.raises(PreparationAdmissionError, match="CORE_PRINCIPAL_REQUIRED"):
                await endpoint.accept_preparation_invocation(
                    serialize_message(envelope), principal="other"
                )
            with pytest.raises(ProtocolError, match="authenticated"):
                await endpoint.accept_invocation(serialize_message(envelope))
            wrong_run = CapabilityRunRef("run-wrong-preparation")
            wrong_invocation = envelope.delivery.invocation.model_copy(update={"run_id": wrong_run})
            wrong = envelope.model_copy(
                update={
                    "message_id": invocation_message_id(wrong_run),
                    "correlation_id": wrong_run,
                    "delivery": envelope.delivery.model_copy(
                        update={"invocation": wrong_invocation}
                    ),
                }
            )
            with pytest.raises(PreparationAdmissionError, match="PREPARATION_AUTHORITY_MISMATCH"):
                await endpoint.accept_preparation_invocation(
                    serialize_message(wrong), principal="boberagent-core"
                )
            expired = permit.model_copy(
                update={
                    "issued_at": datetime.now(UTC) - timedelta(hours=3),
                    "not_before": datetime.now(UTC) - timedelta(hours=2),
                    "expires_at": datetime.now(UTC) - timedelta(hours=1),
                }
            )
            expired_invocation = envelope.delivery.invocation.model_copy(
                update={
                    "inputs": RuntimePreparationInput(
                        schema_version="runtime-preparation-input-v1", permit=expired
                    ).model_dump(mode="json")
                }
            )
            expired_envelope = envelope.model_copy(
                update={
                    "delivery": envelope.delivery.model_copy(
                        update={"invocation": expired_invocation}
                    )
                }
            )
            with pytest.raises(PreparationAdmissionError, match="PREPARATION_AUTHORITY_EXPIRED"):
                await endpoint.accept_preparation_invocation(
                    serialize_message(expired_envelope), principal="boberagent-core"
                )
            wrong_node = envelope.model_copy(update={"node_id": "node-another"})
            with pytest.raises(ProtocolError, match="unavailable"):
                await endpoint.accept_preparation_invocation(
                    serialize_message(wrong_node), principal="boberagent-core"
                )
            assert node.store is not None and node.store.get_run(permit.run_ref) is None
            await endpoint.accept_preparation_invocation(
                serialize_message(envelope), principal="boberagent-core"
            )
            await endpoint.accept_preparation_invocation(
                serialize_message(envelope), principal="boberagent-core"
            )
            conflicting = envelope.model_copy(
                update={
                    "delivery": envelope.delivery.model_copy(
                        update={"allowed_addresses": ("192.0.2.99",)}
                    )
                }
            )
            with pytest.raises(PreparationAdmissionError, match="PREPARATION_AUTHORITY_CONFLICT"):
                await endpoint.accept_preparation_invocation(
                    serialize_message(conflicting), principal="boberagent-core"
                )
        finally:
            await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()


def test_exact_import_chunk_conflicts_and_publication(tmp_path: Path) -> None:
    database, _plan, policy, approvals, registry, _old, request = _setup(tmp_path)
    permit = (
        CoreRuntimePreparationAdmissionService(
            database, policy, approvals, registry, clock=lambda: datetime.now(UTC)
        )
        .admit(request)
        .permit
    )
    assert permit is not None

    async def scenario() -> None:
        node = ExecutionNode(
            NodeConfiguration.for_runtime_directory(tmp_path / "node", configured_node_id=NODE)
        )
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        assert node.preparation is not None
        try:
            await endpoint.accept_preparation_invocation(
                serialize_message(_envelope(permit)), principal="boberagent-core"
            )
            source = permit.spec.source.plan_source
            ref = source.raw_artifact_ref
            transfer = preparation_import_id(permit.permit_ref, ref)
            common: dict[str, Any] = {
                "node_id": NODE,
                "preparation_ref": permit.spec.preparation_ref,
                "permit_ref": permit.permit_ref,
                "run_ref": permit.run_ref,
                "import_id": transfer,
                "artifact_ref": ref,
                "timestamp": datetime.now(UTC),
            }

            async def exchange(message: ImportRequest) -> ImportResponse:
                from boberagent_transport import parse_import_response

                raw = await endpoint.accept_preparation_import(
                    serialize_message(message), principal="boberagent-core"
                )
                return parse_import_response(raw)

            unauthorized = ImportStart(
                **{
                    **common,
                    "artifact_ref": ArtifactRef("artifact-not-in-permit"),
                    "import_id": preparation_import_id(
                        permit.permit_ref, ArtifactRef("artifact-not-in-permit")
                    ),
                },
                message_id=import_message_id(
                    preparation_import_id(permit.permit_ref, ArtifactRef("artifact-not-in-permit")),
                    "start",
                ),
                sha256=source.raw_sha256,
                size_bytes=source.raw_size_bytes,
            )
            assert isinstance(await exchange(unauthorized), ImportRejected)
            start = ImportStart(
                **common,
                message_id=import_message_id(transfer, "start"),
                sha256=source.raw_sha256,
                size_bytes=source.raw_size_bytes,
            )
            wrong_size = start.model_copy(update={"size_bytes": source.raw_size_bytes + 1})
            assert isinstance(await exchange(wrong_size), ImportRejected)
            wrong_preparation = start.model_copy(
                update={"preparation_ref": RuntimePreparationRef("preparation-wrong")}
            )
            assert isinstance(await exchange(wrong_preparation), ImportRejected)
            wrong_run = start.model_copy(update={"run_ref": CapabilityRunRef("run-wrong-import")})
            assert isinstance(await exchange(wrong_run), ImportRejected)
            ready = await exchange(start)
            assert isinstance(ready, ImportReady) and ready.next_offset == 0
            assert await exchange(start) == ready
            with pytest.raises(FileNotFoundError):
                node.preparation.imported_bytes(ref)
            from boberagent_core import (
                ArtifactStorageConfiguration,
                CoreArtifactService,
                FilesystemArtifactStorage,
            )

            artifacts = CoreArtifactService(
                database,
                FilesystemArtifactStorage(
                    ArtifactStorageConfiguration(root=tmp_path / "artifacts")
                ),
            )
            data = artifacts.read_bytes(ref)
            first = data[:17]

            def chunk(offset: int, value: bytes) -> ImportChunk:
                return ImportChunk(
                    **common,
                    message_id=import_message_id(transfer, f"chunk:{offset}"),
                    offset=offset,
                    data=value,
                    chunk_sha256=hashlib.sha256(value).hexdigest(),
                )

            progressed = await exchange(chunk(0, first))
            assert isinstance(progressed, ImportReady) and progressed.next_offset == len(first)
            assert await exchange(chunk(0, first)) == progressed
            conflict = await exchange(chunk(0, b"X" * len(first)))
            assert isinstance(conflict, ImportRejected) and conflict.code == "IMPORT_CHUNK_CONFLICT"
            early = ImportFinalize(**common, message_id=import_message_id(transfer, "finalize"))
            incomplete = await exchange(early)
            assert isinstance(incomplete, ImportRejected) and incomplete.code == "IMPORT_INCOMPLETE"
            offset = len(first)
            while offset < len(data):
                part = data[offset : offset + 31]
                reply = await exchange(chunk(offset, part))
                assert isinstance(reply, ImportReady)
                offset = reply.next_offset
            complete = await exchange(early)
            assert isinstance(complete, ImportCompleted)
            assert complete.sha256 == source.raw_sha256 and complete.size_bytes == len(data)
            duplicate = await exchange(early)
            assert isinstance(duplicate, ImportCompleted) and duplicate.deduplicated
            assert node.preparation.imported_bytes(ref) == data
            assert node.store is not None and node.store.get_artifact(ref) is None
        finally:
            await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()


def test_partial_import_survives_node_restart_and_corrupt_content_is_rejected(
    tmp_path: Path,
) -> None:
    database, _plan, policy, approvals, registry, _old, request = _setup(tmp_path)
    permit = (
        CoreRuntimePreparationAdmissionService(
            database, policy, approvals, registry, clock=lambda: datetime.now(UTC)
        )
        .admit(request)
        .permit
    )
    assert permit is not None

    async def scenario() -> None:
        config = NodeConfiguration.for_runtime_directory(tmp_path / "node", configured_node_id=NODE)
        node = ExecutionNode(config)
        await node.initialize()
        raw = permit.spec.source.plan_source
        ref = raw.raw_artifact_ref
        transfer = preparation_import_id(permit.permit_ref, ref)
        common: dict[str, Any] = {
            "node_id": NODE,
            "preparation_ref": permit.spec.preparation_ref,
            "permit_ref": permit.permit_ref,
            "run_ref": permit.run_ref,
            "import_id": transfer,
            "artifact_ref": ref,
            "timestamp": datetime.now(UTC),
        }

        async def exchange(message: ImportRequest) -> ImportResponse:
            from boberagent_transport import parse_import_response

            response = await ExecutionNodeTransportEndpoint(node).accept_preparation_import(
                serialize_message(message), principal="boberagent-core"
            )
            return parse_import_response(response)

        try:
            await ExecutionNodeTransportEndpoint(node).accept_preparation_invocation(
                serialize_message(_envelope(permit)), principal="boberagent-core"
            )
            start = ImportStart(
                **common,
                message_id=import_message_id(transfer, "start"),
                sha256=raw.raw_sha256,
                size_bytes=raw.raw_size_bytes,
            )
            assert isinstance(await exchange(start), ImportReady)
            corrupt = b"Z" * raw.raw_size_bytes
            first = corrupt[:11]
            chunk = ImportChunk(
                **common,
                message_id=import_message_id(transfer, "chunk:0"),
                offset=0,
                data=first,
                chunk_sha256=hashlib.sha256(first).hexdigest(),
            )
            assert isinstance(await exchange(chunk), ImportReady)
            assert node.preparation is not None
            with pytest.raises(FileNotFoundError):
                node.preparation.imported_bytes(ref)
            await node.shutdown()
            node = ExecutionNode(config)
            await node.initialize()
            status = ImportStatus(**common, message_id=import_message_id(transfer, "status"))
            ready = await exchange(status)
            assert isinstance(ready, ImportReady) and ready.next_offset == len(first)
            remaining = corrupt[len(first) :]
            if remaining:
                reply = await exchange(
                    ImportChunk(
                        **common,
                        message_id=import_message_id(transfer, f"chunk:{len(first)}"),
                        offset=len(first),
                        data=remaining,
                        chunk_sha256=hashlib.sha256(remaining).hexdigest(),
                    )
                )
                assert isinstance(reply, ImportReady)
            failure = await exchange(
                ImportFinalize(**common, message_id=import_message_id(transfer, "finalize"))
            )
            assert isinstance(failure, ImportRejected) and failure.code == "IMPORT_DIGEST_MISMATCH"
            assert node.preparation is not None
            with pytest.raises(FileNotFoundError):
                node.preparation.imported_bytes(ref)
            assert node.store is not None and node.store.get_artifact(ref) is None
        finally:
            await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()
