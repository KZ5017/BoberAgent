"""A real hostile B2 result cannot finalize a Core acquisition."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest
from boberagent_contracts import CapabilityRun, CapabilityRunRef, CapabilityRunStatus
from boberagent_core import (
    ArtifactStorageConfiguration,
    CapabilityRegistrationClient,
    CapabilityRegistry,
    CapabilityRouter,
    CoreArtifactService,
    CoreDatabase,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    FilesystemArtifactStorage,
    ResultIngestionService,
    upgrade_database,
)
from boberagent_core.acquisitions import CorePoCAcquisitionService, PoCAcquisitionStatus
from boberagent_execution_node import ExecutionNodeTransportEndpoint
from boberagent_transport import InMemoryTransport, InvocationDelivery, MissionProjection
from test_core_poc_acquisition import _bounds, _seed
from test_poc_acquisition_b3 import NOW, _node, _server, _zip


@pytest.mark.parametrize("mode", ["hostile", "tool_missing"])
def test_failed_or_hostile_fixture_never_completes_acquisition(tmp_path: Path, mode: str) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(database)
    storage = FilesystemArtifactStorage(
        ArtifactStorageConfiguration(root=tmp_path / "core-artifacts")
    )
    artifacts = CoreArtifactService(database, storage)
    service = CorePoCAcquisitionService(database, artifacts, clock=lambda: NOW)
    _research, candidate_ref, hit_ids, hypothesis = _seed(database)
    with _server(
        _zip("fixture-sha/../escape"),
        repository_uri="https://github.com/example/repo-main",
        historical_ref="branch:old",
    ) as server:
        acquisition = service.create_acquisition(
            mission_ref=hypothesis.mission_ref,
            hypothesis_ref=hypothesis.hypothesis_ref,
            candidate_ref=candidate_ref,
            selected_hit_id=hit_ids[0],
            bounds=_bounds().model_copy(update={"max_download_bytes": 100_000}),
            fixture_port=server.server_port,
        )
        run_ref = CapabilityRunRef(f"run-b3-{mode}")
        invocation = service.build_invocation(acquisition.acquisition_ref, run_ref)
        registry = CapabilityRegistry(database)
        transport = InMemoryTransport()
        registration = CapabilityRegistrationClient(transport, registry)
        router = CapabilityRouter(registry, transport)
        receiver = CoreTransportReceiver(
            database, result_ingestion=ResultIngestionService(database)
        )
        client = CoreTransportClient(transport, receiver)
        copied_curl: Path | None = None
        if mode == "tool_missing":
            installed = shutil.which("curl")
            if installed is None:
                pytest.skip("managed curl >=8.4 is unavailable")
            copied_curl = tmp_path / "curl-disappears-after-handshake"
            shutil.copy2(installed, copied_curl)

        async def scenario() -> None:
            node = _node(tmp_path, curl_override=None if copied_curl is None else str(copied_curl))
            await node.initialize()
            endpoint = ExecutionNodeTransportEndpoint(node)
            transport.register_node(endpoint)
            await transport.connect()
            await registration.refresh_node(endpoint.node_id)
            if copied_curl is not None:
                copied_curl.unlink()
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
            service.record_dispatched(acquisition.acquisition_ref, run_ref)
            await transport.wait_for_idle()
            count = await client.flush_node(endpoint.node_id)
            for _ in range(count):
                await client.receive_one()
            envelope = receiver.result_for_run(run_ref)
            assert envelope is not None
            assert "acquisition_receipt" not in envelope.result.outcome.details
            if mode == "hostile":
                assert envelope.result.execution_status is CapabilityRunStatus.COMPLETED
                assert envelope.result.outcome.code == "ARCHIVE_PATH_INVALID"
                assert len(envelope.result.artifacts) == 1
                assert envelope.result.artifacts[0].artifact_type == "poc.source.raw"
                assert not artifacts.content_available(envelope.result.artifacts[0].artifact_id)
                assert (
                    service.reconcile(acquisition.acquisition_ref).status
                    is PoCAcquisitionStatus.REJECTED
                )
            else:
                assert envelope.result.execution_status is CapabilityRunStatus.FAILED
                assert envelope.result.artifacts == ()
                assert (
                    service.reconcile(acquisition.acquisition_ref).status
                    is PoCAcquisitionStatus.FAILED
                )
            await transport.disconnect()
            await node.shutdown()

        try:
            asyncio.run(scenario())
        finally:
            database.dispose()
    assert server.requests == (["/revision", "/archive.zip"] if mode == "hostile" else [])
