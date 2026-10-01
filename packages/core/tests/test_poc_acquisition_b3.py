"""B3: real fixture acquisition through Router, Result ingestion and Artifact sync."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import shutil
import stat
import struct
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from boberagent_contracts import (
    ArtifactRef,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    PoCSourceAcquisitionReceipt,
)
from boberagent_core import (
    ArtifactStorageConfiguration,
    CapabilityRegistrationClient,
    CapabilityRegistry,
    CapabilityRouter,
    CoreArtifactReceiver,
    CoreArtifactService,
    CoreDatabase,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    FilesystemArtifactStorage,
    ResultIngestionService,
    upgrade_database,
)
from boberagent_core.acquisitions import (
    CorePoCAcquisitionService,
    PoCAcquisitionError,
    PoCAcquisitionStatus,
)
from boberagent_execution_node import (
    ArtifactSyncCoordinator,
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
    ToolConfiguration,
)
from boberagent_transport import (
    ArtifactChunk,
    ArtifactTransferRequest,
    ArtifactTransferResponse,
    ArtifactTransport,
    InMemoryTransport,
    InvocationDelivery,
    MissionProjection,
)
from pydantic import ValidationError
from test_core_poc_acquisition import _bounds, _seed

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY_PATH = ROOT / "capabilities/poc-source-acquisition"
NODE_ID = "node-b3-fixture"
NOW = datetime(2026, 9, 27, tzinfo=UTC)
SHA = "a" * 40


def _zip(name: str = "fixture-sha/README.md", *, github_ut: bool = False) -> bytes:
    output = io.BytesIO()
    timestamp_extra = struct.pack("<HHBI", 0x5455, 5, 1, 1_700_000_000) if github_ut else b""
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        root = zipfile.ZipInfo("fixture-sha/")
        root.create_system = 3
        root.external_attr = (stat.S_IFDIR | 0o755) << 16
        root.extra = timestamp_extra
        archive.writestr(root, b"")
        item = zipfile.ZipInfo(name)
        item.create_system = 3
        item.external_attr = (stat.S_IFREG | 0o644) << 16
        item.compress_type = zipfile.ZIP_DEFLATED
        item.extra = timestamp_extra
        archive.writestr(item, b"source evidence only\n")
    return output.getvalue()


class _Fixture(ThreadingHTTPServer):
    archive: bytes
    revision: bytes
    requests: list[str]


@contextmanager
def _server(archive: bytes, *, repository_uri: str, historical_ref: str) -> Iterator[_Fixture]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            server.requests.append(self.path)
            if self.path == "/revision":
                body = server.revision
            elif self.path == "/archive.zip":
                body = server.archive
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            return

    server = _Fixture(("127.0.0.1", 0), Handler)
    server.archive = archive
    server.revision = json.dumps(
        {
            "repository_uri": repository_uri,
            "provider_repository_id": 42,
            "historical_ref": historical_ref,
            "resolved_commit_sha": SHA,
        },
        sort_keys=True,
    ).encode()
    server.requests = []
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _node(tmp_path: Path, *, curl_override: str | None = None) -> ExecutionNode:
    curl = curl_override or shutil.which("curl")
    if curl is None:
        pytest.skip("managed curl >=8.4 is unavailable")
    return ExecutionNode(
        NodeConfiguration.for_runtime_directory(
            tmp_path / "node",
            capability_paths=(CAPABILITY_PATH,),
            configured_node_id=NODE_ID,
            tools={"curl": ToolConfiguration(executable=curl, version_args=("--version",))},
        )
    )


def _coordinator(node: ExecutionNode, transport: ArtifactTransport) -> ArtifactSyncCoordinator:
    assert node.store is not None
    assert node.identity is not None
    return ArtifactSyncCoordinator(
        store=node.store,
        spool_root=node.configuration.artifact_spool_root,
        node_id=str(node.identity.node_id),
        transport=transport,
        clock=lambda: datetime.now(UTC),
        chunk_size=31,
    )


class _DisconnectAfterChunk:
    def __init__(self, transport: InMemoryTransport) -> None:
        self._transport = transport
        self._disconnected = False

    @property
    def connected(self) -> bool:
        return self._transport.connected

    async def exchange_artifact(self, request: ArtifactTransferRequest) -> ArtifactTransferResponse:
        response = await self._transport.exchange_artifact(request)
        if isinstance(request, ArtifactChunk) and not self._disconnected:
            self._disconnected = True
            await self._transport.disconnect()
        return response


@pytest.mark.parametrize("first", ["raw", "manifest"])
def test_real_b3_result_before_artifacts_and_replay_after_core_node_restart(
    tmp_path: Path, first: str, *, emit_summary: bool = False
) -> None:
    database_path = tmp_path / "core.sqlite3"
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(database)
    storage = FilesystemArtifactStorage(
        ArtifactStorageConfiguration(root=tmp_path / "core-artifacts")
    )
    artifacts = CoreArtifactService(database, storage)
    acquisition_service = CorePoCAcquisitionService(database, artifacts, clock=lambda: NOW)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    repository_uri = "https://github.com/example/repo-main"
    archive = _zip()
    with _server(archive, repository_uri=repository_uri, historical_ref="branch:old") as server:
        acquisition = acquisition_service.create_acquisition(
            mission_ref=hypothesis.mission_ref,
            hypothesis_ref=hypothesis.hypothesis_ref,
            candidate_ref=candidate_ref,
            selected_hit_id=hit_ids[0],
            bounds=_bounds().model_copy(update={"max_download_bytes": 100_000}),
            fixture_port=server.server_port,
        )
        run_ref = CapabilityRunRef(f"run-b3-{first}")
        invocation = acquisition_service.build_invocation(acquisition.acquisition_ref, run_ref)
        assert invocation.inputs["source_kind"] == "loopback_fixture"
        registry = CapabilityRegistry(database)
        transport = InMemoryTransport()
        transport.register_artifact_receiver(CoreArtifactReceiver(database, storage))
        registration = CapabilityRegistrationClient(transport, registry)
        router = CapabilityRouter(registry, transport)
        receiver = CoreTransportReceiver(
            database, result_ingestion=ResultIngestionService(database)
        )
        client = CoreTransportClient(transport, receiver)

        async def scenario() -> tuple[PoCSourceAcquisitionReceipt, ExecutionNode]:
            node = _node(tmp_path)
            await node.initialize()
            endpoint = ExecutionNodeTransportEndpoint(node)
            transport.register_node(endpoint)
            await transport.connect()
            providers = (await registration.refresh_node(endpoint.node_id))[1]
            acquisition_providers = tuple(
                provider
                for provider in providers
                if provider.capability_id == invocation.capability_id
            )
            assert len(acquisition_providers) == 1
            assert acquisition_providers[0].availability.value == "AVAILABLE"
            with database.unit_of_work() as work:
                work.runs.add(
                    CapabilityRun(
                        run_id=run_ref,
                        mission_ref=hypothesis.mission_ref,
                        capability_id=invocation.capability_id,
                        operation=invocation.operation,
                        status=CapabilityRunStatus.CREATED,
                        created_at=NOW,
                    )
                )
            provider = router.select_provider(
                capability_id=invocation.capability_id, operation="acquire"
            )
            await router.dispatch(
                invocation=invocation,
                delivery=InvocationDelivery(
                    invocation=invocation,
                    mission=MissionProjection(mission_ref=hypothesis.mission_ref),
                ),
                provider=provider,
            )
            acquisition_service.record_dispatched(acquisition.acquisition_ref, run_ref)
            await transport.wait_for_idle()
            count = await client.flush_node(endpoint.node_id)
            for _ in range(count):
                await client.receive_one()
            envelope = receiver.result_for_run(run_ref)
            assert envelope is not None
            assert envelope.result.execution_status is CapabilityRunStatus.COMPLETED
            receipt = PoCSourceAcquisitionReceipt.model_validate(
                envelope.result.outcome.details["acquisition_receipt"]
            )
            persisted = acquisition_service.get(acquisition.acquisition_ref)
            assert persisted is not None
            acquisition_service.validate_receipt(persisted, receipt)
            for changed in (
                {"fixture_port": server.server_port + 1},
                {"source_kind": "github_repository"},
                {"provider_repository_id": 999},
                {"run_ref": CapabilityRunRef("run-foreign")},
                {"acquisition_ref": "poc-acquisition-foreign"},
            ):
                with pytest.raises(PoCAcquisitionError):
                    acquisition_service.validate_receipt(
                        persisted, receipt.model_copy(update=changed)
                    )
            receipt_json = receipt.model_dump(mode="json")
            for invalid_payload in (
                {"raw_archive_sha256": "0" * 64},
                {"raw_archive_size_bytes": receipt.raw_archive_size_bytes + 1},
                {"manifest": receipt.raw_source.model_dump(mode="json")},
                {
                    "raw_source": {
                        **receipt.raw_source.model_dump(mode="json"),
                        "artifact_id": str(ArtifactRef("artifact-foreign")),
                        "created_by_run": "run-foreign",
                    }
                },
            ):
                with pytest.raises(ValidationError):
                    PoCSourceAcquisitionReceipt.model_validate({**receipt_json, **invalid_payload})
            assert len(envelope.result.artifacts) == 2
            assert receipt.raw_source in envelope.result.artifacts
            assert receipt.manifest in envelope.result.artifacts
            assert receipt.raw_source.created_by_run == receipt.manifest.created_by_run == run_ref
            assert receipt.raw_source.artifact_id != receipt.manifest.artifact_id
            assert node.store is not None
            for descriptor in (receipt.raw_source, receipt.manifest):
                record = node.store.get_artifact(descriptor.artifact_id)
                assert record is not None and record.descriptor == descriptor
                assert not any(node.configuration.workspace_root.iterdir())
            assert (
                acquisition_service.reconcile(acquisition.acquisition_ref).status
                is PoCAcquisitionStatus.AWAITING_ARTIFACT
            )
            await transport.disconnect()
            await node.shutdown()
            restarted = _node(tmp_path)
            await restarted.initialize()
            transport.register_node(ExecutionNodeTransportEndpoint(restarted), replace=True)
            await transport.connect()
            return receipt, restarted

        receipt, restarted = asyncio.run(scenario())
        database.dispose()
        reopened = CoreDatabase(DatabaseConfig.sqlite(database_path))
        try:
            restarted_storage = FilesystemArtifactStorage(
                ArtifactStorageConfiguration(root=tmp_path / "core-artifacts")
            )
            reopened_artifacts = CoreArtifactService(reopened, restarted_storage)
            resumed = CorePoCAcquisitionService(reopened, reopened_artifacts, clock=lambda: NOW)
            transport.register_artifact_receiver(CoreArtifactReceiver(reopened, restarted_storage))

            async def finish() -> None:
                sequence = (
                    (receipt.raw_source, receipt.manifest)
                    if first == "raw"
                    else (receipt.manifest, receipt.raw_source)
                )
                coordinator = _coordinator(restarted, transport)
                partial = await _coordinator(
                    restarted, _DisconnectAfterChunk(transport)
                ).synchronize(sequence[0].artifact_id)
                assert not partial.synchronized
                assert not reopened_artifacts.content_available(sequence[0].artifact_id)
                assert (
                    resumed.reconcile(acquisition.acquisition_ref).status
                    is PoCAcquisitionStatus.AWAITING_ARTIFACT
                )
                await transport.connect()
                first_outcome = await coordinator.synchronize(sequence[0].artifact_id)
                assert first_outcome.synchronized and first_outcome.chunks_sent > 1
                assert (
                    resumed.reconcile(acquisition.acquisition_ref).status
                    is PoCAcquisitionStatus.AWAITING_ARTIFACT
                )
                second_outcome = await coordinator.synchronize(sequence[1].artifact_id)
                assert second_outcome.synchronized
                completed = resumed.reconcile(acquisition.acquisition_ref)
                assert completed.status is PoCAcquisitionStatus.COMPLETED
                assert resumed.reconcile(acquisition.acquisition_ref) == completed
                assert completed.receipt == receipt and completed.run_ref == run_ref
                assert completed.selected_hit_id == hit_ids[0]
                assert completed.node_id == NODE_ID
                assert completed.routing_provider_id is not None
                assert completed.resolved_commit_sha == SHA
                assert reopened_artifacts.read_bytes(receipt.raw_source.artifact_id) == archive
                manifest = reopened_artifacts.read_bytes(receipt.manifest.artifact_id)
                assert hashlib.sha256(manifest).hexdigest() == receipt.manifest_sha256
                assert receipt.raw_archive_sha256 == hashlib.sha256(archive).hexdigest()
                if emit_summary:
                    print(
                        json.dumps(
                            {
                                "acquisition_ref": str(completed.acquisition_ref),
                                "candidate_ref": str(completed.candidate_ref),
                                "selected_hit_id": completed.selected_hit_id,
                                "run_ref": str(run_ref),
                                "node_id": completed.node_id,
                                "provider_id": str(completed.routing_provider_id),
                                "resolved_revision": completed.resolved_commit_sha,
                                "raw_artifact_ref": str(receipt.raw_source.artifact_id),
                                "raw_sha256": receipt.raw_archive_sha256,
                                "manifest_artifact_ref": str(receipt.manifest.artifact_id),
                                "manifest_sha256": receipt.manifest_sha256,
                                "status": completed.status.value,
                            },
                            sort_keys=True,
                        )
                    )
                await transport.disconnect()
                await restarted.shutdown()

            asyncio.run(finish())
        finally:
            reopened.dispose()
    assert server.requests == ["/revision", "/archive.zip"]
