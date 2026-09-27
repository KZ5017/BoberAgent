"""Opt-in public GitHub acquisition through the real Core/MCP/Kali path.

No repository content is inspected for meaning, extracted, installed, or executed.
``--check-config`` is offline and read-only; only ``--live-network`` dispatches.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from boberagent_cli.operator_env import operator_environment
from boberagent_contracts import (
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    PoCAcquisitionBounds,
    PoCAcquisitionRef,
    PoCSourceAcquisitionInput,
    PoCSourceAcquisitionReceipt,
)
from boberagent_core import (
    ArtifactStorageConfiguration,
    CapabilityRegistry,
    CapabilityRouter,
    CapabilityRoutingError,
    CoreArtifactReceiver,
    CoreArtifactService,
    CoreDatabase,
    CoreMcpNodeConnection,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    FilesystemArtifactStorage,
    ResultIngestionService,
    upgrade_database,
)
from boberagent_core.acquisitions import CorePoCAcquisitionService, PoCAcquisitionStatus
from boberagent_core.research import (
    CoreResearchService,
    HitDecision,
    PoCCandidate,
    PoCCandidateRef,
    ResearchSourceHit,
    ResearchStatus,
    SourceClass,
)
from boberagent_transport import InvocationDelivery, MissionProjection
from boberagent_transport_mcp import McpClientConfiguration
from pydantic import SecretStr


class SmokeStop(RuntimeError):
    """Expected environment/provider/policy stop; never a successful B5 run."""


@dataclass(frozen=True)
class Selection:
    candidate: PoCCandidate
    hit: ResearchSourceHit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live-network", action="store_true", help="authorize one real acquisition")
    mode.add_argument("--check-config", action="store_true", help="offline, read-only preflight")
    parser.add_argument("--database", type=Path, required=True, help="existing M20-A Core database")
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--candidate-ref", required=True)
    parser.add_argument("--hit-id", type=int, required=True, help="explicit historical source hit")
    parser.add_argument("--endpoint", required=True, help="real Kali MCP URL")
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--allow-insecure-remote-transport", action="store_true")
    parser.add_argument("--token-environment-variable", default="BOBERAGENT_MCP_TOKEN")
    parser.add_argument("--run-timeout-seconds", type=float, default=240)
    return parser


def _bounds() -> PoCAcquisitionBounds:
    """Explicit small-repository limits; choose a lead that fits, never retry unbounded."""
    return PoCAcquisitionBounds(
        max_download_bytes=32 * 1024 * 1024,
        max_uncompressed_bytes=128 * 1024 * 1024,
        max_single_file_bytes=32 * 1024 * 1024,
        max_file_count=2500,
        max_directory_depth=32,
        max_path_length=512,
        max_compression_ratio=200,
        max_outbound_requests=8,
        max_redirects=1,
        timeout_seconds=180,
    )


def _configuration(args: argparse.Namespace) -> McpClientConfiguration:
    if not args.database.is_absolute() or not args.database.is_file():
        raise SmokeStop("setup: --database must name an existing absolute Core SQLite file")
    if not args.artifact_root.is_absolute() or args.artifact_root.is_file():
        raise SmokeStop("setup: --artifact-root must be an absolute directory path")
    if args.ca_file is not None and not args.ca_file.is_file():
        raise SmokeStop("setup: --ca-file does not exist")
    if not 0 < args.run_timeout_seconds <= 900:
        raise SmokeStop("setup: --run-timeout-seconds must be in (0, 900]")
    if args.hit_id < 1:
        raise SmokeStop("selection: --hit-id must be a positive historical row ID")
    try:
        PoCCandidateRef(args.candidate_ref)
    except ValueError as error:
        raise SmokeStop("selection: --candidate-ref is invalid") from error
    try:
        environment = operator_environment(
            os.environ, project_root=Path(__file__).resolve().parents[2]
        )
    except ValueError as error:
        raise SmokeStop("setup: operator environment file is invalid or unavailable") from error
    token = environment.get(args.token_environment_variable)
    if not token:
        raise SmokeStop(
            f"setup: bearer token environment variable is unset: {args.token_environment_variable}"
        )
    try:
        return McpClientConfiguration(
            endpoint_url=args.endpoint,
            node_id=args.node_id,
            bearer_token=SecretStr(token),
            verify_tls=args.ca_file if args.ca_file is not None else True,
            allow_insecure_remote_transport=args.allow_insecure_remote_transport,
        )
    except ValueError as error:
        raise SmokeStop("setup: MCP endpoint/TLS/Node configuration is invalid") from error


def _selection(database: CoreDatabase, candidate_ref: PoCCandidateRef, hit_id: int) -> Selection:
    research = CoreResearchService(database)
    candidate = research.get_candidate(candidate_ref)
    if candidate is None:
        raise SmokeStop("selection: PoCCandidateRef is not in this Core database")
    attempts = research.list_attempts(candidate.hypothesis_ref)
    hits = (
        hit
        for attempt in attempts
        if attempt.status in {ResearchStatus.FOUND, ResearchStatus.PARTIAL}
        for hit in research.list_hits(attempt.attempt_ref)
        if hit.hit_id == hit_id
    )
    hit = next(hits, None)
    if (
        hit is None
        or hit.candidate_ref != candidate_ref
        or hit.decision is HitDecision.REJECTED
        or hit.provider_id != "github-repository-search-v1"
        or hit.source.source_class is not SourceClass.REPOSITORY
        or hit.source.repository_identity is None
        or hit.source.source_uri != hit.source.repository_identity
        or hit.source.revision_claim is None
        or hit.source.provider_result_id is None
    ):
        raise SmokeStop("selection: historical hit is not an admitted GitHub lead for candidate")
    try:
        PoCSourceAcquisitionInput.github_repository_uri(hit.source.repository_identity)
        PoCSourceAcquisitionInput.mutable_branch_claim(hit.source.revision_claim)
        if int(hit.source.provider_result_id) < 1:
            raise ValueError("invalid provider repository ID")
    except ValueError as error:
        raise SmokeStop(
            "selection: historical hit is not a supported public GitHub claim"
        ) from error
    return Selection(candidate=candidate, hit=hit)


def _preview(selection: Selection, bounds: PoCAcquisitionBounds) -> None:
    source = selection.hit.source
    print(f"Candidate: {selection.candidate.candidate_ref}")
    print(f"Historical hit: {selection.hit.hit_id} ({selection.hit.decision.value})")
    print(f"Repository: {source.repository_identity}")
    print(f"Provider result ID: {source.provider_result_id}")
    print(f"Historical branch: {source.revision_claim}")
    print(f"Bounds: {bounds.model_dump_json()}")
    print("Public egress: api.github.com, codeload.github.com only")


_EXPECTED_OUTCOMES = {
    "DEPENDENCY_UNAVAILABLE": "required Node dependency unavailable",
    "EXECUTION_TIMED_OUT": "bounded acquisition timed out",
    "TOOL_EXECUTION_FAILED": "managed curl execution failed",
    "GITHUB_RATE_LIMITED": "GitHub rate limited/denied",
    "REPOSITORY_IDENTITY_MISMATCH": "repository identity changed",
    "REPOSITORY_UNAVAILABLE": "repository unavailable",
    "MUTABLE_REF_UNAVAILABLE": "historical branch unavailable",
    "REVISION_RESOLUTION_FAILED": "revision unavailable",
    "TREE_TRUNCATED": "tree truncated",
    "SUBMODULE_UNSUPPORTED": "submodule/Gitlink unsupported",
    "LFS_UNSUPPORTED": "Git LFS unsupported",
    "DOWNLOAD_LIMIT_EXCEEDED": "archive/response exceeded bounds",
    "ARCHIVE_LIMIT_EXCEEDED": "archive structure exceeded bounds",
    "ARCHIVE_UNSUPPORTED": "archive structure unsupported",
    "ARCHIVE_COLLISION": "archive names collide",
    "ARCHIVE_ENTRY_TYPE_UNSUPPORTED": "archive entry type unsupported",
    "ARCHIVE_PATH_INVALID": "archive path unsafe",
    "ARCHIVE_REDIRECT_REJECTED": "archive redirect rejected",
    "SOURCE_INTEGRITY_INVALID": "source integrity/structure rejected",
    "GITHUB_RESPONSE_INVALID": "GitHub response invalid",
}


async def _live(
    args: argparse.Namespace,
    database: CoreDatabase,
    selection: Selection,
    configuration: McpClientConfiguration,
    bounds: PoCAcquisitionBounds,
) -> tuple[str, str]:
    storage = FilesystemArtifactStorage(ArtifactStorageConfiguration(root=args.artifact_root))
    artifacts = CoreArtifactService(database, storage)
    acquisitions = CorePoCAcquisitionService(database, artifacts)
    registry = CapabilityRegistry(database)
    connection = CoreMcpNodeConnection(configuration, registry)
    transport = connection.transport
    router = CapabilityRouter(registry, transport)
    receiver = CoreTransportReceiver(database, result_ingestion=ResultIngestionService(database))
    client = CoreTransportClient(transport, receiver)
    try:
        try:
            advertisement, _ = await connection.connect_and_refresh()
        except Exception as error:
            raise SmokeStop(
                f"environment: real MCP connection/handshake failed ({type(error).__name__})"
            ) from error
        if advertisement.node_id != args.node_id:
            raise SmokeStop("environment: Node identity differs from explicit --node-id")
        try:
            provider = router.select_provider(
                capability_id="poc.source_acquisition", operation="acquire", node_id=args.node_id
            )
        except CapabilityRoutingError as error:
            raise SmokeStop(
                "provider unavailable: Node must advertise poc.source_acquisition:acquire and curl >=8.4,<9"
            ) from error
        print(f"Node/provider: {advertisement.node_id} / {provider.provider_id}")
        acquisition = acquisitions.create_acquisition(
            mission_ref=selection.candidate.mission_ref,
            hypothesis_ref=selection.candidate.hypothesis_ref,
            candidate_ref=selection.candidate.candidate_ref,
            selected_hit_id=selection.hit.hit_id,
            bounds=bounds,
        )
        run_ref = CapabilityRunRef(f"run-m20b5-{uuid4().hex}")
        invocation = acquisitions.build_invocation(acquisition.acquisition_ref, run_ref)
        with database.unit_of_work() as work:
            work.runs.add(
                CapabilityRun(
                    run_id=run_ref,
                    mission_ref=acquisition.mission_ref,
                    capability_id=invocation.capability_id,
                    operation=invocation.operation,
                    status=CapabilityRunStatus.CREATED,
                    created_at=datetime.now(UTC),
                )
            )
        print(f"PoCAcquisitionRef: {acquisition.acquisition_ref}")
        print(f"CapabilityRunRef: {run_ref}")
        try:
            await router.dispatch(
                invocation=invocation,
                delivery=InvocationDelivery(
                    invocation=invocation,
                    mission=MissionProjection(mission_ref=acquisition.mission_ref),
                ),
                provider=provider,
            )
        except Exception as error:
            acquisitions.fail(acquisition.acquisition_ref, "transport dispatch failed")
            raise SmokeStop(
                f"environment: transport dispatch failed ({type(error).__name__})"
            ) from error
        dispatched = acquisitions.record_dispatched(acquisition.acquisition_ref, run_ref)
        print(f"Acquisition after Router dispatch: {dispatched.status.value}")
        deadline = asyncio.get_running_loop().time() + args.run_timeout_seconds
        envelope = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                count = await client.flush_node(args.node_id)
                for _ in range(count):
                    await client.receive_one()
            except Exception as error:
                raise SmokeStop(
                    f"environment: Result delivery failed ({type(error).__name__})"
                ) from error
            envelope = receiver.result_for_run(run_ref)
            if envelope is not None:
                break
            await asyncio.sleep(0.5)
        if envelope is None:
            raise SmokeStop(
                "environment: timed out waiting for terminal Result; inspect persisted Run"
            )
        result = envelope.result
        state = acquisitions.reconcile(acquisition.acquisition_ref)
        print(
            f"Result: {result.execution_status.value} / {result.outcome.category.value} / {result.outcome.code}"
        )
        print(f"After Result, before Artifact sync: {state.status.value}")
        if result.outcome.code != "SOURCE_ACQUIRED":
            reason = _EXPECTED_OUTCOMES.get(result.outcome.code or "")
            if reason is None:
                raise RuntimeError(f"unexpected acquisition outcome code: {result.outcome.code}")
            raise SmokeStop(
                f"safe provider/policy stop: {reason} ({result.outcome.code}); B5 is not complete"
            )
        if result.execution_status is not CapabilityRunStatus.COMPLETED:
            raise RuntimeError("SOURCE_ACQUIRED has a non-COMPLETED execution state")
        if state.status is not PoCAcquisitionStatus.AWAITING_ARTIFACT:
            raise RuntimeError("Result alone unexpectedly completed acquisition")
        receipt = PoCSourceAcquisitionReceipt.model_validate(
            result.outcome.details["acquisition_receipt"]
        )
        print(
            f"Fresh repository identity: {receipt.validated_repository_uri} / {receipt.validated_provider_repository_id}"
        )
        print(f"Branch → full commit SHA: {receipt.historical_ref} → {receipt.resolved_commit_sha}")
        print(f"Resolved at: {receipt.resolved_at.isoformat()}")
        print(f"Git tree: {receipt.resolved_tree_sha}; complete/validated, no Gitlink")
        print(
            f"API endpoints: {receipt.repository_validation_uri}, {receipt.resolution_uri}, {receipt.tree_uri}"
        )
        print(f"SHA-addressed archive request: {receipt.archive_request_uri}")
        print(f"Validated final archive: {receipt.final_archive_uri}")
        print(
            f"HTTP: metadata accepted 200; archive redirect accepted; final archive accepted 200; requests={receipt.request_count}, redirects={receipt.redirect_count}"
        )
        print(
            f"Raw ZIP: {receipt.raw_source.artifact_id} sha256={receipt.raw_archive_sha256} size={receipt.raw_archive_size_bytes}"
        )
        print(f"Manifest: {receipt.manifest.artifact_id} sha256={receipt.manifest_sha256}")
        try:
            summary = await transport.synchronize_artifacts(
                CoreArtifactReceiver(database, storage), limit=10, chunk_size=64 * 1024
            )
        except Exception as error:
            raise SmokeStop(
                f"Artifact sync failed ({type(error).__name__}); B5 is not complete"
            ) from error
        print(
            f"Artifact synchronization: attempted={summary.attempted}, synchronized={summary.synchronized}, failed={summary.failed}"
        )
        if not all(
            artifacts.content_available(item.artifact_id)
            for item in (receipt.raw_source, receipt.manifest)
        ):
            raise SmokeStop("Artifact sync incomplete; both Core copies are required")
        completed = acquisitions.reconcile(acquisition.acquisition_ref)
        if completed.status is not PoCAcquisitionStatus.COMPLETED:
            raise RuntimeError(f"Artifact-verified finalization failed: {completed.status.value}")
        _verify_core_artifacts(artifacts, receipt)
        return str(acquisition.acquisition_ref), str(run_ref)
    finally:
        await connection.disconnect()


def _verify_core_artifacts(
    artifacts: CoreArtifactService, receipt: PoCSourceAcquisitionReceipt
) -> None:
    for descriptor in (receipt.raw_source, receipt.manifest):
        digest = hashlib.sha256()
        size = 0
        with artifacts.open_content(descriptor.artifact_id) as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        if digest.hexdigest() != descriptor.sha256 or size != descriptor.size_bytes:
            raise RuntimeError("Core Artifact bytes differ from persisted descriptor")
    manifest = json.loads(artifacts.read_bytes(receipt.manifest.artifact_id))
    if manifest.get("format_version") != "poc-source-manifest-v1":
        raise RuntimeError("structural manifest version is invalid")
    if manifest.get("raw_archive_sha256") != receipt.raw_archive_sha256:
        raise RuntimeError("structural manifest is not bound to the raw ZIP")
    print(
        "Structural manifest: "
        f"entries={manifest['entry_count']} "
        f"uncompressed_bytes={manifest['total_uncompressed_bytes']} "
        f"root={manifest['archive_root_prefix']}"
    )


async def _run(args: argparse.Namespace) -> None:
    configuration = _configuration(args)
    bounds = _bounds()
    database = CoreDatabase(DatabaseConfig.sqlite(args.database))
    try:
        selection = _selection(database, PoCCandidateRef(args.candidate_ref), args.hit_id)
        _preview(selection, bounds)
        if args.check_config:
            print(
                "OFFLINE CONFIGURATION VALID; no MCP connection, GitHub request, or database write"
            )
            return
        # This database comes from M20-A; upgrade only after the explicit live opt-in.
        upgrade_database(database)
        acquisition_ref, run_ref = await _live(args, database, selection, configuration, bounds)
    finally:
        database.dispose()
    reopened = CoreDatabase(DatabaseConfig.sqlite(args.database))
    try:
        artifacts = CoreArtifactService(
            reopened,
            FilesystemArtifactStorage(ArtifactStorageConfiguration(root=args.artifact_root)),
        )
        persisted = CorePoCAcquisitionService(reopened, artifacts).get(
            PoCAcquisitionRef(acquisition_ref)
        )
        if persisted is None or persisted.status is not PoCAcquisitionStatus.COMPLETED:
            raise RuntimeError("PoCAcquisition did not survive Core reopen")
        if (
            persisted.candidate_ref != selection.candidate.candidate_ref
            or persisted.selected_hit_id != selection.hit.hit_id
            or persisted.historical_ref != selection.hit.source.revision_claim
            or persisted.run_ref is None
            or str(persisted.run_ref) != run_ref
            or persisted.node_id != args.node_id
            or persisted.routing_provider_id is None
            or persisted.receipt is None
        ):
            raise RuntimeError("durable acquisition provenance differs after reopen")
        _verify_core_artifacts(artifacts, persisted.receipt)
        with reopened.unit_of_work() as work:
            decision = work.routing_decisions.get(persisted.run_ref)
            run = work.runs.get(persisted.run_ref)
        if (
            decision is None
            or decision.node_id != persisted.node_id
            or decision.provider_id != persisted.routing_provider_id
            or run is None
            or run.mission_ref != persisted.mission_ref
        ):
            raise RuntimeError("durable Run or Router decision differs after reopen")
        print(f"SUCCESS: {persisted.acquisition_ref} COMPLETED after Core reopen; no re-fetch")
    finally:
        reopened.dispose()


def main() -> None:
    try:
        asyncio.run(_run(_parser().parse_args()))
    except SmokeStop as error:
        print(f"B5 STOP: {error}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
