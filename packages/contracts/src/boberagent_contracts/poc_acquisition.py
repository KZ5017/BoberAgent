"""Bounded cross-machine values for the planned PoC source-acquisition capability.

These are not Core research/acquisition records. The future Node returns a receipt in
``CapabilityOutcome.details["acquisition_receipt"]``; Core validates it again.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from ._base import ContractModel
from .artifact import ArtifactDescriptor, Sha256Digest
from .refs import CapabilityRunRef, PoCAcquisitionRef

type FullGitCommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
type AcquisitionName = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
]
_REPOSITORY_PART = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_BRANCH = re.compile(r"^branch:[A-Za-z0-9._/-]{1,240}$")


class PoCAcquisitionBounds(ContractModel):
    """Every security-critical acquisition limit is explicit; no unbounded default exists."""

    max_download_bytes: int = Field(ge=1, le=16 * 1024**3)
    max_uncompressed_bytes: int = Field(ge=1, le=64 * 1024**3)
    max_single_file_bytes: int = Field(ge=1, le=16 * 1024**3)
    max_file_count: int = Field(ge=1, le=1_000_000)
    max_directory_depth: int = Field(ge=1, le=256)
    max_path_length: int = Field(ge=1, le=4096)
    max_compression_ratio: float = Field(ge=1, le=10_000)
    max_outbound_requests: int = Field(ge=1, le=100)
    max_redirects: int = Field(ge=0, le=20)
    timeout_seconds: float = Field(gt=0, le=3600)

    @model_validator(mode="after")
    def coherent_size_limits(self) -> Self:
        if self.max_single_file_bytes > self.max_uncompressed_bytes:
            raise ValueError("single-file limit cannot exceed uncompressed-total limit")
        return self


class PoCSourceAcquisitionInput(ContractModel):
    """Only the bounded source claim needed by the future Node operation."""

    acquisition_ref: PoCAcquisitionRef
    source_kind: Literal["github_repository", "loopback_fixture"]
    repository_uri: str = Field(min_length=1, max_length=255)
    provider_repository_id: int = Field(ge=1)
    historical_ref: str = Field(min_length=8, max_length=247)
    bounds: PoCAcquisitionBounds
    fixture_port: int | None = Field(default=None, ge=1, le=65535)

    @model_validator(mode="after")
    def fixture_mode(self) -> Self:
        if (self.source_kind == "loopback_fixture") != (self.fixture_port is not None):
            raise ValueError("fixture port is required only for loopback fixture mode")
        return self

    @field_validator("repository_uri")
    @classmethod
    def github_repository_uri(cls, value: str) -> str:
        parsed = urlsplit(value)
        parts = parsed.path.strip("/").split("/")
        if (
            parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or parsed.query
            or parsed.fragment
            or len(parts) != 2
            or any(_REPOSITORY_PART.fullmatch(part) is None for part in parts)
            or parsed.path != f"/{parts[0]}/{parts[1]}"
        ):
            raise ValueError("repository URI must be a canonical public GitHub repository URL")
        return value

    @field_validator("historical_ref")
    @classmethod
    def mutable_branch_claim(cls, value: str) -> str:
        if _BRANCH.fullmatch(value) is None or ".." in value or value.endswith("/"):
            raise ValueError("historical ref must be a bounded branch:<name> claim")
        return value


class PoCSourceAcquisitionReceipt(ContractModel):
    """Typed provenance claim, not proof of Core Artifact availability or source safety."""

    acquisition_ref: PoCAcquisitionRef
    run_ref: CapabilityRunRef
    source_kind: Literal["github_repository", "loopback_fixture"]
    repository_uri: str = Field(min_length=1, max_length=255)
    provider_repository_id: int = Field(ge=1)
    historical_ref: str = Field(min_length=8, max_length=247)
    fixture_port: int | None = Field(default=None, ge=1, le=65535)
    resolved_commit_sha: FullGitCommitSha
    resolved_at: AwareDatetime
    resolution_uri: str = Field(min_length=1, max_length=2048)
    final_archive_uri: str = Field(min_length=1, max_length=2048)
    archive_representation: Literal["github_zip"]
    adapter_id: AcquisitionName
    adapter_version: AcquisitionName
    request_count: int = Field(ge=1, le=100)
    redirect_count: int = Field(ge=0, le=20)
    raw_source: ArtifactDescriptor
    raw_archive_sha256: Sha256Digest
    raw_archive_size_bytes: int = Field(ge=0)
    manifest: ArtifactDescriptor
    manifest_sha256: Sha256Digest

    @model_validator(mode="after")
    def consistent_artifacts(self) -> Self:
        if self.raw_source.artifact_id == self.manifest.artifact_id:
            raise ValueError("source and manifest ArtifactRefs must differ")
        if (
            self.raw_source.artifact_type != "poc.source.raw"
            or self.manifest.artifact_type != "poc.source.manifest"
            or self.raw_source.media_type != "application/zip"
            or self.manifest.media_type != "application/json"
        ):
            raise ValueError("source ZIP and structural manifest Artifact roles are invalid")
        if (
            self.raw_source.created_by_run != self.run_ref
            or self.manifest.created_by_run != self.run_ref
        ):
            raise ValueError("source and manifest must be produced by the receipt Run")
        if (
            self.raw_source.sha256 != self.raw_archive_sha256
            or self.raw_source.size_bytes != self.raw_archive_size_bytes
            or self.manifest.sha256 != self.manifest_sha256
            or self.manifest.size_bytes is None
        ):
            raise ValueError("receipt hashes and sizes must agree with Artifact descriptors")
        PoCSourceAcquisitionInput.github_repository_uri(self.repository_uri)
        PoCSourceAcquisitionInput.mutable_branch_claim(self.historical_ref)
        if self.source_kind == "github_repository":
            if self.fixture_port is not None:
                raise ValueError("GitHub receipt cannot carry a fixture port")
            for uri in (self.resolution_uri, self.final_archive_uri):
                parsed = urlsplit(uri)
                if (
                    parsed.scheme != "https"
                    or parsed.netloc not in {"api.github.com", "codeload.github.com"}
                    or parsed.query
                    or parsed.fragment
                    or not parsed.path.startswith("/")
                ):
                    raise ValueError("GitHub provenance URI must use approved API/archive hosts")
        else:
            if self.fixture_port is None:
                raise ValueError("fixture receipt requires a loopback port")
            for uri in (self.resolution_uri, self.final_archive_uri):
                parsed = urlsplit(uri)
                if (
                    parsed.scheme != "http"
                    or parsed.hostname != "127.0.0.1"
                    or parsed.port != self.fixture_port
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.query
                    or parsed.fragment
                    or not parsed.path.startswith("/")
                ):
                    raise ValueError("fixture provenance URI must remain on its loopback port")
        if self.redirect_count > self.request_count:
            raise ValueError("redirect count cannot exceed request count")
        return self
