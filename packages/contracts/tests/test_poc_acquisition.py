"""M20-B1 cross-machine acquisition values remain bounded and infrastructure-free."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from boberagent_contracts import (
    ArtifactDescriptor,
    ArtifactRef,
    CapabilityDefinition,
    CapabilityRunRef,
    PoCAcquisitionBounds,
    PoCAcquisitionRef,
    PoCSourceAcquisitionInput,
    PoCSourceAcquisitionReceipt,
    StorageRef,
    contract_schema_bundle,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 26, tzinfo=UTC)
SHA = "a" * 40
RAW_HASH = "b" * 64
MANIFEST_HASH = "c" * 64


def bounds() -> PoCAcquisitionBounds:
    return PoCAcquisitionBounds(
        max_download_bytes=1024,
        max_uncompressed_bytes=4096,
        max_single_file_bytes=2048,
        max_file_count=20,
        max_directory_depth=5,
        max_path_length=255,
        max_compression_ratio=100,
        max_outbound_requests=3,
        max_redirects=1,
        timeout_seconds=30,
    )


def receipt() -> PoCSourceAcquisitionReceipt:
    run = CapabilityRunRef("run-acquire")
    return PoCSourceAcquisitionReceipt(
        acquisition_ref=PoCAcquisitionRef("poc-acquisition-test"),
        run_ref=run,
        source_kind="github_repository",
        repository_uri="https://github.com/example/repo",
        provider_repository_id=42,
        historical_ref="branch:main",
        resolved_commit_sha=SHA,
        resolved_at=NOW,
        resolution_uri="https://api.github.com/repos/example/repo/commits/main",
        final_archive_uri=f"https://codeload.github.com/example/repo/zip/{SHA}",
        archive_representation="github_zip",
        adapter_id="fixture-adapter",
        adapter_version="1.0",
        request_count=2,
        redirect_count=1,
        raw_source=ArtifactDescriptor(
            artifact_id=ArtifactRef("artifact-raw"),
            artifact_type="poc.source.raw",
            storage_ref=StorageRef("node:raw"),
            created_by_run=run,
            created_at=NOW,
            sha256=RAW_HASH,
            size_bytes=10,
            media_type="application/zip",
        ),
        raw_archive_sha256=RAW_HASH,
        raw_archive_size_bytes=10,
        manifest=ArtifactDescriptor(
            artifact_id=ArtifactRef("artifact-manifest"),
            artifact_type="poc.source.manifest",
            storage_ref=StorageRef("node:manifest"),
            created_by_run=run,
            created_at=NOW,
            sha256=MANIFEST_HASH,
            size_bytes=20,
            media_type="application/json",
        ),
        manifest_sha256=MANIFEST_HASH,
    )


def test_bounds_are_explicit_and_validated() -> None:
    assert bounds().max_download_bytes == 1024
    for update in (
        {"max_download_bytes": 0},
        {"max_outbound_requests": 0},
        {"max_redirects": -1},
        {"timeout_seconds": 0},
        {"max_single_file_bytes": 5000},
    ):
        with pytest.raises(ValidationError):
            PoCAcquisitionBounds.model_validate({**bounds().model_dump(), **update})
    with pytest.raises(ValidationError):
        PoCAcquisitionBounds.model_validate({})


def test_input_is_typed_and_excludes_core_research_objects() -> None:
    value = PoCSourceAcquisitionInput(
        acquisition_ref=PoCAcquisitionRef("poc-acquisition-test"),
        source_kind="github_repository",
        repository_uri="https://github.com/example/repo",
        provider_repository_id=42,
        historical_ref="branch:main",
        bounds=bounds(),
    )
    assert PoCSourceAcquisitionInput.model_validate_json(value.model_dump_json()) == value
    assert set(value.model_dump()) == {
        "acquisition_ref",
        "source_kind",
        "repository_uri",
        "provider_repository_id",
        "historical_ref",
        "bounds",
    }
    for update in (
        {"repository_uri": "https://other.test/repo"},
        {"repository_uri": "https://github.com/example/repo?token=secret"},
        {"historical_ref": "branch:../main"},
        {"historical_ref": SHA},
    ):
        with pytest.raises(ValidationError):
            PoCSourceAcquisitionInput.model_validate({**value.model_dump(), **update})


def test_receipt_distinguishes_git_snapshot_from_exact_archive_bytes() -> None:
    value = receipt()
    assert value.resolved_commit_sha != value.raw_archive_sha256
    assert value.raw_source.artifact_id != value.manifest.artifact_id
    assert PoCSourceAcquisitionReceipt.model_validate_json(value.model_dump_json()) == value
    for update in (
        {"resolved_commit_sha": "branch:main"},
        {"resolved_commit_sha": "a" * 7},
        {"raw_archive_sha256": "d" * 64},
        {"manifest_sha256": "d" * 64},
        {"manifest": value.raw_source.model_dump(mode="json")},
        {"unexpected": "not a Contract field"},
    ):
        with pytest.raises(ValidationError):
            PoCSourceAcquisitionReceipt.model_validate({**value.model_dump(mode="json"), **update})


def test_static_planned_definition_is_valid_without_a_live_provider() -> None:
    root = Path(__file__).resolve().parents[3]
    path = root / "docs/m20/poc_source_acquisition.definition.json"
    definition = CapabilityDefinition.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert definition.capability_id == "poc.source_acquisition"
    assert tuple(operation.name for operation in definition.operations) == ("acquire",)
    assert (
        definition.operations[0].input_schema.ref
        == "boberagent-contracts:PoCSourceAcquisitionInput"
    )
    assert definition.operations[0].output_schema is not None
    assert "PoCSourceAcquisitionInput" in contract_schema_bundle()["$defs"]
    assert "PoCSourceAcquisitionReceipt" in contract_schema_bundle()["$defs"]
