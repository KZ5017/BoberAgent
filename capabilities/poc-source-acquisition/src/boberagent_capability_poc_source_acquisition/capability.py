"""Fixture-only B2 source acquisition through SDK-managed services."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import ClassVar

from boberagent_contracts import (
    ArtifactDescriptor,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunStatus,
    Diagnostic,
    DiagnosticSeverity,
    PoCSourceAcquisitionInput,
    PoCSourceAcquisitionReceipt,
)
from boberagent_sdk import Capability, ExecutionContext, InputError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .downloader import ManagedFixtureDownloader
from .errors import AcquisitionRejected
from .inventory import inventory_zip


class _FixtureRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_uri: str
    provider_repository_id: int
    historical_ref: str
    resolved_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")


class PoCSourceAcquisitionCapability(Capability):
    """Acquire one loopback fixture ZIP; GitHub support remains unavailable until B4."""

    capability_id: ClassVar[str] = "poc.source_acquisition"

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        if operation != "acquire" or not isinstance(inputs, PoCSourceAcquisitionInput):
            raise InputError("poc.source_acquisition requires validated acquire inputs")
        if inputs.source_kind != "loopback_fixture" or inputs.fixture_port is None:
            raise InputError("this provider supports only explicit loopback_fixture acquisition")
        await ctx.cancellation.checkpoint()
        workspace = await ctx.workspace.create(purpose="poc-source-acquisition")
        raw_artifact: ArtifactDescriptor | None = None
        try:
            downloader = ManagedFixtureDownloader(
                ctx, workspace.path, port=inputs.fixture_port, bounds=inputs.bounds
            )
            revision_response = await downloader.fetch("/revision")
            try:
                revision = _FixtureRevision.model_validate_json(revision_response.path.read_bytes())
            except (ValidationError, ValueError) as error:
                raise AcquisitionRejected(
                    "SOURCE_INTEGRITY_INVALID", "fixture revision claim is invalid"
                ) from error
            if (
                revision.repository_uri != inputs.repository_uri
                or revision.provider_repository_id != inputs.provider_repository_id
                or revision.historical_ref != inputs.historical_ref
            ):
                raise AcquisitionRejected(
                    "SOURCE_INTEGRITY_INVALID", "fixture source identity differs from authorization"
                )
            resolved_at = ctx.clock.now()
            archive_response = await downloader.fetch("/archive.zip")
            raw_sha, raw_size = _hash_file(archive_response.path)
            raw_artifact = await ctx.artifacts.create_from_file(
                artifact_type="poc.source.raw",
                path=archive_response.path,
                media_type="application/zip",
                metadata={
                    "source_kind": "loopback_fixture",
                    "acquisition_ref": str(inputs.acquisition_ref),
                    "resolved_commit_sha": revision.resolved_commit_sha,
                },
            )
            if raw_artifact.sha256 != raw_sha or raw_artifact.size_bytes != raw_size:
                raise AcquisitionRejected(
                    "SOURCE_INTEGRITY_INVALID", "spooled raw Artifact differs from downloaded bytes"
                )
            inventory = inventory_zip(
                archive_response.path,
                inputs.bounds,
                resolved_commit_sha=revision.resolved_commit_sha,
                raw_archive_sha256=raw_sha,
                raw_archive_size_bytes=raw_size,
            )
            manifest = await ctx.artifacts.create_from_bytes(
                artifact_type="poc.source.manifest",
                data=inventory["manifest_bytes"],
                media_type="application/json",
                metadata={
                    "format_version": "poc-source-manifest-v1",
                    "acquisition_ref": str(inputs.acquisition_ref),
                },
            )
            if manifest.sha256 is None:
                raise AcquisitionRejected("SOURCE_INTEGRITY_INVALID", "manifest hash is missing")
            receipt = PoCSourceAcquisitionReceipt(
                acquisition_ref=inputs.acquisition_ref,
                run_ref=ctx.invocation.run_id,
                source_kind="loopback_fixture",
                repository_uri=inputs.repository_uri,
                provider_repository_id=inputs.provider_repository_id,
                historical_ref=inputs.historical_ref,
                fixture_port=inputs.fixture_port,
                resolved_commit_sha=revision.resolved_commit_sha,
                resolved_at=resolved_at,
                resolution_uri=revision_response.final_uri,
                final_archive_uri=archive_response.final_uri,
                archive_representation="github_zip",
                adapter_id="managed-curl-loopback-fixture",
                adapter_version="1.0",
                request_count=downloader.request_count,
                redirect_count=downloader.redirect_count,
                raw_source=raw_artifact,
                raw_archive_sha256=raw_sha,
                raw_archive_size_bytes=raw_size,
                manifest=manifest,
                manifest_sha256=manifest.sha256,
            )
            return CapabilityResult(
                run_ref=ctx.invocation.run_id,
                execution_status=CapabilityRunStatus.COMPLETED,
                outcome=CapabilityOutcome(
                    category=CapabilityOutcomeCategory.SUCCESS,
                    code="SOURCE_ACQUIRED",
                    summary="Bounded fixture source and structural manifest were preserved.",
                    details={"acquisition_receipt": receipt.model_dump(mode="json")},
                ),
                artifacts=(raw_artifact, manifest),
            )
        except AcquisitionRejected as error:
            return CapabilityResult(
                run_ref=ctx.invocation.run_id,
                execution_status=CapabilityRunStatus.COMPLETED,
                outcome=CapabilityOutcome(
                    category=CapabilityOutcomeCategory.UNKNOWN,
                    code=error.code,
                    summary="Fixture source could not become a complete acquisition.",
                ),
                artifacts=() if raw_artifact is None else (raw_artifact,),
                diagnostics=(
                    Diagnostic(
                        code=error.code,
                        severity=DiagnosticSeverity.WARNING,
                        message=error.message,
                        occurred_at=ctx.clock.now(),
                        run_ref=ctx.invocation.run_id,
                        artifact_refs=() if raw_artifact is None else (raw_artifact.artifact_id,),
                    ),
                ),
            )
        finally:
            await ctx.workspace.cleanup(workspace.workspace_ref)


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
