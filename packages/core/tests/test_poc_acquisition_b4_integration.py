"""Offline B4 integration: real Node/runtime/Router/sync, test-owned curl shim, no Internet."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from boberagent_contracts import (
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
from boberagent_core.acquisitions import CorePoCAcquisitionService, PoCAcquisitionStatus
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
    ToolConfiguration,
)
from boberagent_transport import InMemoryTransport, InvocationDelivery, MissionProjection
from test_core_poc_acquisition import _bounds, _seed
from test_poc_acquisition_b3 import CAPABILITY_PATH, NOW, _coordinator, _zip

ROOT = "https://api.github.com/repos/example/repo-main"
REPO = "https://github.com/example/repo-main"
SHA = "b" * 40
TREE_SHA = "c" * 40
BRANCH = f"{ROOT}/branches/old"
COMMIT = f"{ROOT}/git/commits/{SHA}"
TREE = f"{ROOT}/git/trees/{TREE_SHA}?recursive=1"
ARCHIVE = f"{ROOT}/zipball/{SHA}"
CODELOAD = f"https://codeload.github.com/example/repo-main/legacy.zip/{SHA}"


def _reply_set(archive: bytes) -> dict[str, tuple[int, bytes, str]]:
    return {
        ROOT: (
            200,
            json.dumps(
                {
                    "id": 42,
                    "full_name": "example/repo-main",
                    "html_url": REPO,
                    "private": False,
                    "default_branch": "new-default",
                    "owner": {"login": "example"},
                }
            ).encode(),
            "",
        ),
        BRANCH: (200, json.dumps({"name": "old", "commit": {"sha": SHA}}).encode(), ""),
        COMMIT: (200, json.dumps({"sha": SHA, "tree": {"sha": TREE_SHA}}).encode(), ""),
        TREE: (
            200,
            json.dumps(
                {
                    "sha": TREE_SHA,
                    "truncated": False,
                    "tree": [
                        {"path": "README.md", "mode": "100644", "type": "blob", "sha": "d" * 40}
                    ],
                }
            ).encode(),
            "",
        ),
        ARCHIVE: (302, b"", CODELOAD),
        CODELOAD: (200, archive, ""),
    }


def _curl_shim(tmp_path: Path, replies: dict[str, tuple[int, bytes, str]]) -> tuple[Path, Path]:
    """An executable that simulates curl responses but cannot make a network request."""

    recorded = tmp_path / "requested-uris.jsonl"
    encoded = {
        uri: [status, base64.b64encode(body).decode("ascii"), redirect]
        for uri, (status, body, redirect) in replies.items()
    }
    script = tmp_path / "offline-curl"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import base64, json, pathlib, sys\n"
        f"RESPONSES = {encoded!r}\n"
        f"RECORD = pathlib.Path({str(recorded)!r})\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('curl 8.5.0'); raise SystemExit(0)\n"
        "args = sys.argv[1:]\n"
        "assert args[0] == '-q' and args[args.index('--proto')+1] == '=https'\n"
        "assert args[args.index('--proxy')+1] == ''\n"
        "assert args[args.index('--noproxy')+1] == '*'\n"
        "assert '--location' not in args and '-L' not in args\n"
        "uri = args[-1]\n"
        "RECORD.open('a', encoding='utf-8').write(json.dumps(uri) + '\\n')\n"
        "status, encoded, redirect = RESPONSES[uri]\n"
        "body = base64.b64decode(encoded)\n"
        "limit = int(args[args.index('--max-filesize')+1])\n"
        "out = pathlib.Path(args[args.index('--output')+1])\n"
        "if len(body) > limit:\n"
        "    out.write_bytes(body[:limit]); raise SystemExit(63)\n"
        "out.write_bytes(body)\n"
        "sys.stdout.write(str(status) + '\\n' + redirect)\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    return script, recorded


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("success", "SOURCE_ACQUIRED"),
        ("identity", "REPOSITORY_IDENTITY_MISMATCH"),
        ("missing_branch", "MUTABLE_REF_UNAVAILABLE"),
        ("truncated", "TREE_TRUNCATED"),
        ("gitlink", "SUBMODULE_UNSUPPORTED"),
        ("lfs", "LFS_UNSUPPORTED"),
        ("redirect", "ARCHIVE_REDIRECT_REJECTED"),
        ("oversize", "DOWNLOAD_LIMIT_EXCEEDED"),
        ("hostile", "ARCHIVE_PATH_INVALID"),
    ],
)
def test_mocked_github_core_node_core(
    tmp_path: Path, case: str, expected: str, *, emit_summary: bool = False
) -> None:
    """Historical hit stays unchanged while current main/old resolves to pinned SHA B."""

    archive = (
        _zip(github_ut=case == "success") if case != "hostile" else _zip("fixture-sha/../escape")
    )
    if case == "lfs":

        def _archive(entries: list[tuple[str, bytes, int]]) -> bytes:
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for name, data, mode in entries:
                    item = zipfile.ZipInfo(name)
                    item.create_system = 3
                    item.external_attr = mode << 16
                    bundle.writestr(item, data)
            return output.getvalue()

        archive = _archive(
            [
                (
                    f"repo-{SHA}/pointer",
                    b"version https://git-lfs.github.com/spec/v1\n"
                    + b"oid sha256:"
                    + b"0" * 64
                    + b"\nsize 1\n",
                    0o100644,
                )
            ]
        )
    replies = _reply_set(archive)
    if case == "identity":
        replies[ROOT] = (
            200,
            json.dumps(
                {
                    "id": 99,
                    "full_name": "example/repo-main",
                    "html_url": REPO,
                    "private": False,
                    "owner": {"login": "example"},
                }
            ).encode(),
            "",
        )
    elif case == "missing_branch":
        replies[BRANCH] = (404, b"", "")
    elif case == "truncated":
        replies[TREE] = (
            200,
            json.dumps(
                {
                    "sha": TREE_SHA,
                    "truncated": True,
                    "tree": [],
                }
            ).encode(),
            "",
        )
    elif case == "gitlink":
        replies[TREE] = (
            200,
            json.dumps(
                {
                    "sha": TREE_SHA,
                    "truncated": False,
                    "tree": [
                        {"path": "vendor", "mode": "160000", "type": "commit", "sha": "d" * 40}
                    ],
                }
            ).encode(),
            "",
        )
    elif case == "redirect":
        replies[ARCHIVE] = (302, b"", "https://example.invalid/archive")
    elif case == "oversize":
        replies[CODELOAD] = (200, b"x" * 200_000, "")
    shim, recorded = _curl_shim(tmp_path, replies)

    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(database)
    storage = FilesystemArtifactStorage(
        ArtifactStorageConfiguration(root=tmp_path / "core-artifacts")
    )
    artifacts = CoreArtifactService(database, storage)
    service = CorePoCAcquisitionService(database, artifacts, clock=lambda: NOW)
    research, candidate_ref, hit_ids, hypothesis = _seed(database)
    historical = research.list_hits(
        research.list_attempts(hypothesis.hypothesis_ref)[0].attempt_ref
    )[0]
    acquisition = service.create_acquisition(
        mission_ref=hypothesis.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate_ref,
        selected_hit_id=hit_ids[0],
        bounds=_bounds().model_copy(
            update={
                "max_download_bytes": 100_000,
                "max_outbound_requests": 8,
                "max_redirects": 2,
            }
        ),
    )
    run_ref = CapabilityRunRef(f"run-b4-{case}")
    invocation = service.build_invocation(acquisition.acquisition_ref, run_ref)
    assert invocation.inputs["source_kind"] == "github_repository"
    transport = InMemoryTransport()
    transport.register_artifact_receiver(CoreArtifactReceiver(database, storage))
    registry = CapabilityRegistry(database)
    registration = CapabilityRegistrationClient(transport, registry)
    router = CapabilityRouter(registry, transport)
    receiver = CoreTransportReceiver(database, result_ingestion=ResultIngestionService(database))
    client = CoreTransportClient(transport, receiver)

    async def scenario() -> None:
        node = ExecutionNode(
            NodeConfiguration.for_runtime_directory(
                tmp_path / "node",
                capability_paths=(CAPABILITY_PATH,),
                configured_node_id=f"node-b4-{case}",
                tools={
                    "curl": ToolConfiguration(executable=str(shim), version_args=("--version",))
                },
            )
        )
        try:
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
            service.record_dispatched(acquisition.acquisition_ref, run_ref)
            await transport.wait_for_idle()
            count = await client.flush_node(endpoint.node_id)
            for _ in range(count):
                await client.receive_one()
            envelope = receiver.result_for_run(run_ref)
            assert envelope is not None
            assert envelope.result.outcome.code == expected
            assert envelope.result.observations == ()
            assert envelope.result.findings == ()
            assert envelope.result.effects == ()
            if case == "success":
                receipt = PoCSourceAcquisitionReceipt.model_validate(
                    envelope.result.outcome.details["acquisition_receipt"]
                )
                assert receipt.historical_ref == "branch:old"
                assert receipt.resolved_commit_sha == SHA
                assert (
                    receipt.provider_repository_id == receipt.validated_provider_repository_id == 42
                )
                assert receipt.archive_request_uri == ARCHIVE
                assert receipt.final_archive_uri == CODELOAD
                assert receipt.raw_archive_sha256 == hashlib.sha256(archive).hexdigest()
                assert len(envelope.result.artifacts) == 2
                assert (
                    service.reconcile(acquisition.acquisition_ref).status
                    is PoCAcquisitionStatus.AWAITING_ARTIFACT
                )
                coordinator = _coordinator(node, transport)
                assert (await coordinator.synchronize(receipt.raw_source.artifact_id)).synchronized
                assert (
                    service.reconcile(acquisition.acquisition_ref).status
                    is PoCAcquisitionStatus.AWAITING_ARTIFACT
                )
                assert (await coordinator.synchronize(receipt.manifest.artifact_id)).synchronized
                completed = service.reconcile(acquisition.acquisition_ref)
                assert completed.status is PoCAcquisitionStatus.COMPLETED
                assert service.reconcile(acquisition.acquisition_ref) == completed
                assert artifacts.read_bytes(receipt.raw_source.artifact_id) == archive
                assert artifacts.content_available(receipt.manifest.artifact_id)
                if emit_summary:
                    print(
                        json.dumps(
                            {
                                "historical_repository_identity": historical.source.repository_identity,
                                "historical_branch": historical.source.revision_claim,
                                "fresh_repository_identity": receipt.validated_repository_uri,
                                "resolved_commit_sha": receipt.resolved_commit_sha,
                                "raw_artifact_ref": str(receipt.raw_source.artifact_id),
                                "raw_sha256": receipt.raw_archive_sha256,
                                "manifest_artifact_ref": str(receipt.manifest.artifact_id),
                                "manifest_sha256": receipt.manifest_sha256,
                                "status": completed.status.value,
                            },
                            sort_keys=True,
                        )
                    )
            else:
                assert "acquisition_receipt" not in envelope.result.outcome.details
                assert (
                    service.reconcile(acquisition.acquisition_ref).status
                    is PoCAcquisitionStatus.REJECTED
                )
                assert len(envelope.result.artifacts) == (1 if case in {"lfs", "hostile"} else 0)
            with database.unit_of_work() as work:
                assert work.runs.get(run_ref) is not None
                assert work.routing_decisions.get(run_ref) is not None
                assert len(work.acquisitions.list_for_candidate(candidate_ref)) == 1
        finally:
            await node.shutdown()

    try:
        asyncio.run(scenario())
        seen = [json.loads(line) for line in recorded.read_text(encoding="utf-8").splitlines()]
        assert seen[:1] == [ROOT]
        assert all(
            uri.startswith("https://api.github.com/")
            or uri.startswith("https://codeload.github.com/")
            for uri in seen
        )
        if case == "success":
            assert seen == [ROOT, BRANCH, COMMIT, TREE, ARCHIVE, CODELOAD]
            assert historical.source.revision_claim == "branch:old"
            assert research.list_hits(historical.attempt_ref)[0] == historical
    finally:
        database.dispose()
