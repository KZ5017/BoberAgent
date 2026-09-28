"""Core-owned versioned inspection; evidence is read only from Core Artifacts."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from boberagent_contracts import MissionRef, PoCAcquisitionRef
from pydantic import Field, model_validator

from boberagent_core.acquisitions.models import PoCAcquisitionStatus
from boberagent_core.artifacts import CoreArtifactService
from boberagent_core.clock import utc_now
from boberagent_core.models import CoreModel
from boberagent_core.persistence import CoreDatabase
from boberagent_core.research.models import PoCCandidateRef, VulnerabilityHypothesisRef

from .evidence import InspectionError, VerifiedSource, _safe_path, line_span
from .models import (
    InspectionDocument,
    InspectionLimits,
    InspectionStatus,
    PoCInspection,
    PoCInspectionRef,
    SourceCitation,
)
from .semantic_analysis import analyze_semantics
from .semantic_models import (
    PROFILE_ID as SEMANTIC_PROFILE_ID,
)
from .semantic_models import (
    PROFILE_VERSION as SEMANTIC_PROFILE_VERSION,
)
from .semantic_models import (
    SemanticInspectionDocument,
    SemanticInspectionLimits,
)

PROFILE_ID = "m20-c1-evidence"
PROFILE_VERSION = "1"


class CitationSpan(CoreModel):
    path: str = Field(min_length=1, max_length=4096)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    reader_id: str = Field(min_length=1, max_length=128)
    reader_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def nonempty_ordered_span(self) -> CitationSpan:
        if self.end <= self.start:
            raise ValueError("citation span must be nonempty and ordered")
        return self


class CorePoCInspectionService:
    """Explicitly pumped, restart-safe C1 evidence and C2 semantic profiles."""

    def __init__(
        self,
        database: CoreDatabase,
        artifacts: CoreArtifactService,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._database = database
        self._artifacts = artifacts
        self._clock = clock

    def create(
        self,
        *,
        mission_ref: MissionRef,
        hypothesis_ref: VulnerabilityHypothesisRef,
        candidate_ref: PoCCandidateRef,
        acquisition_ref: PoCAcquisitionRef,
        limits: InspectionLimits | SemanticInspectionLimits | None = None,
        selected_paths: tuple[str, ...] = (),
        profile_id: str = PROFILE_ID,
        profile_version: str = PROFILE_VERSION,
        force_new: bool = False,
    ) -> PoCInspection:
        """Bind only a completed, correctly owned acquisition and its two Artifacts."""

        limits = limits or InspectionLimits()
        if isinstance(limits, SemanticInspectionLimits) != (profile_id == SEMANTIC_PROFILE_ID):
            raise InspectionError("INSPECTION_CONFIG_INVALID")
        if profile_id == SEMANTIC_PROFILE_ID and profile_version != SEMANTIC_PROFILE_VERSION:
            raise InspectionError("INSPECTION_CONFIG_INVALID")
        if (
            len(selected_paths) > limits.max_zip_entries
            or len(selected_paths) != len(set(selected_paths))
            or tuple(sorted(selected_paths)) != selected_paths
        ):
            raise InspectionError("INSPECTION_CONFIG_INVALID")
        try:
            for path in selected_paths:
                _safe_path(path)
        except (TypeError, ValueError) as error:
            raise InspectionError("INSPECTION_CONFIG_INVALID") from error
        config = {
            "limits": limits.model_dump(mode="json"),
            "selected_paths": selected_paths,
        }
        fingerprint = hashlib.sha256(
            json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self._database.unit_of_work() as work:
            mission = work.missions.get(mission_ref)
            hypothesis = work.research.get_hypothesis(hypothesis_ref)
            candidate = work.research.get_candidate(candidate_ref)
            acquisition = work.acquisitions.get(acquisition_ref)
            if (
                mission is None
                or hypothesis is None
                or hypothesis.mission_ref != mission_ref
                or candidate is None
                or candidate.mission_ref != mission_ref
                or candidate.hypothesis_ref != hypothesis_ref
                or acquisition is None
                or acquisition.status is not PoCAcquisitionStatus.COMPLETED
                or acquisition.mission_ref != mission_ref
                or acquisition.hypothesis_ref != hypothesis_ref
                or acquisition.candidate_ref != candidate_ref
                or acquisition.receipt is None
                or acquisition.resolved_commit_sha is None
            ):
                raise InspectionError("ACQUISITION_NOT_INSPECTABLE")
            receipt = acquisition.receipt
            raw_record = work.artifacts.get_record(receipt.raw_source.artifact_id)
            manifest_record = work.artifacts.get_record(receipt.manifest.artifact_id)
            if (
                raw_record is None
                or manifest_record is None
                or raw_record.descriptor != receipt.raw_source
                or manifest_record.descriptor != receipt.manifest
                or receipt.raw_archive_sha256 != receipt.raw_source.sha256
                or receipt.raw_archive_size_bytes != receipt.raw_source.size_bytes
                or receipt.manifest_sha256 != receipt.manifest.sha256
            ):
                raise InspectionError("ACQUISITION_ARTIFACT_CONFLICT")
            if not force_new:
                for existing in work.inspections.list_for_acquisition(acquisition_ref):
                    if (
                        existing.raw_sha256 == receipt.raw_archive_sha256
                        and existing.manifest_sha256 == receipt.manifest_sha256
                        and existing.profile_id == profile_id
                        and existing.profile_version == profile_version
                        and existing.config_fingerprint == fingerprint
                        and existing.status
                        in {InspectionStatus.COMPLETED, InspectionStatus.REQUESTED}
                    ):
                        return existing
            inspection = PoCInspection(
                inspection_ref=PoCInspectionRef(f"poc-inspection-{uuid4().hex}"),
                mission_ref=mission_ref,
                hypothesis_ref=hypothesis_ref,
                candidate_ref=candidate_ref,
                acquisition_ref=acquisition_ref,
                raw_artifact_ref=receipt.raw_source.artifact_id,
                raw_sha256=receipt.raw_archive_sha256,
                raw_size_bytes=receipt.raw_archive_size_bytes,
                manifest_artifact_ref=receipt.manifest.artifact_id,
                manifest_sha256=receipt.manifest_sha256,
                resolved_commit_sha=receipt.resolved_commit_sha,
                profile_id=profile_id,
                profile_version=profile_version,
                config_fingerprint=fingerprint,
                limits=limits,
                selected_paths=selected_paths,
                status=InspectionStatus.REQUESTED,
                created_at=self._now(),
            )
            work.inspections.add(inspection)
            return inspection

    def create_semantic(
        self,
        *,
        mission_ref: MissionRef,
        hypothesis_ref: VulnerabilityHypothesisRef,
        candidate_ref: PoCCandidateRef,
        acquisition_ref: PoCAcquisitionRef,
        limits: SemanticInspectionLimits | None = None,
        selected_paths: tuple[str, ...] = (),
        force_new: bool = False,
    ) -> PoCInspection:
        """Create a distinct C2 attempt; empty selection means bounded manifest selection."""
        return self.create(
            mission_ref=mission_ref,
            hypothesis_ref=hypothesis_ref,
            candidate_ref=candidate_ref,
            acquisition_ref=acquisition_ref,
            limits=limits or SemanticInspectionLimits(),
            selected_paths=selected_paths,
            profile_id=SEMANTIC_PROFILE_ID,
            profile_version=SEMANTIC_PROFILE_VERSION,
            force_new=force_new,
        )

    def get(self, inspection_ref: PoCInspectionRef) -> PoCInspection | None:
        with self._database.unit_of_work() as work:
            return work.inspections.get(inspection_ref)

    def list_for_acquisition(self, acquisition_ref: PoCAcquisitionRef) -> tuple[PoCInspection, ...]:
        with self._database.unit_of_work() as work:
            return work.inspections.list_for_acquisition(acquisition_ref)

    def inspect(
        self, inspection_ref: PoCInspectionRef, *, spans: tuple[CitationSpan, ...] = ()
    ) -> PoCInspection:
        """Validate exact bytes and persist the selected deterministic profile output."""

        with self._database.unit_of_work() as work:
            current = work.inspections.get(inspection_ref)
            if current is None:
                raise InspectionError("INSPECTION_NOT_FOUND")
            if current.status is InspectionStatus.COMPLETED:
                return current
            if current.status is not InspectionStatus.REQUESTED:
                raise InspectionError("INSPECTION_NOT_REQUESTED")
            current = work.inspections.update(
                current.model_copy(
                    update={"status": InspectionStatus.INSPECTING, "started_at": self._now()}
                )
            )
        try:
            deadline = time.monotonic() + current.limits.max_wall_seconds
            source = VerifiedSource(current, self._artifacts, deadline=deadline)
            if current.profile_id == SEMANTIC_PROFILE_ID:
                if current.profile_version != SEMANTIC_PROFILE_VERSION or spans:
                    raise InspectionError("INSPECTION_CONFIG_INVALID")
                semantic = analyze_semantics(source)
                return self._finish(current, InspectionStatus.COMPLETED, document=semantic)
            if len(spans) > current.limits.max_citations:
                raise InspectionError("INSPECTION_LIMIT_EXCEEDED")
            if any(span.path not in current.selected_paths for span in spans):
                raise InspectionError("INSPECTION_CONFIG_INVALID")
            paths = set(current.selected_paths)
            verified: dict[str, bytes] = {}
            total = 0
            for path in sorted(paths):
                entry = source.entries.get(path)
                if (
                    entry is not None
                    and entry.size_bytes is not None
                    and total + entry.size_bytes > current.limits.max_total_verified_bytes
                ):
                    raise InspectionError("INSPECTION_LIMIT_EXCEEDED")
                content = source.verify_entry(path)
                total += len(content)
                if total > current.limits.max_total_verified_bytes:
                    raise InspectionError("INSPECTION_LIMIT_EXCEEDED")
                verified[path] = content
            citations: list[SourceCitation] = []
            for span in spans:
                entry = source.entries[span.path]
                assert entry.sha256 is not None
                citation = SourceCitation(
                    raw_artifact_ref=current.raw_artifact_ref,
                    raw_sha256=current.raw_sha256,
                    manifest_artifact_ref=current.manifest_artifact_ref,
                    manifest_sha256=current.manifest_sha256,
                    path=span.path,
                    entry_sha256=entry.sha256,
                    start=span.start,
                    end=span.end,
                    reader_id=span.reader_id,
                    reader_version=span.reader_version,
                )
                source.validate_citation(citation, verified[span.path])
                citations.append(citation)
            document = InspectionDocument(
                manifest_validated=True,
                zip_reconciled=True,
                verified_paths=tuple(sorted(verified)),
                unverified_paths=tuple(sorted(set(source.entries) - set(verified))),
                citations=tuple(citations),
            )
        except InspectionError as error:
            return self._finish(current, InspectionStatus.FAILED, diagnostic=error.code)
        except Exception:
            # Internal extractor defects are NOT coverage gaps. Never serialize
            # exception text (which could contain hostile source or credentials).
            self._finish(current, InspectionStatus.FAILED, diagnostic="INSPECTOR_INTERNAL_ERROR")
            raise InspectionError("INSPECTOR_INTERNAL_ERROR") from None
        return self._finish(current, InspectionStatus.COMPLETED, document=document)

    def validate_citation(self, inspection_ref: PoCInspectionRef, citation: SourceCitation) -> None:
        current = self._completed(inspection_ref)
        source = VerifiedSource(
            current, self._artifacts, deadline=time.monotonic() + current.limits.max_wall_seconds
        )
        content = source.verify_entry(citation.path)
        source.validate_citation(citation, content)

    def read_citation(self, inspection_ref: PoCInspectionRef, citation: SourceCitation) -> bytes:
        current = self._completed(inspection_ref)
        assert current.document is not None
        if citation not in current.document.citations:
            raise InspectionError("CITATION_INVALID")
        source = VerifiedSource(
            current, self._artifacts, deadline=time.monotonic() + current.limits.max_wall_seconds
        )
        content = source.verify_entry(citation.path)
        source.validate_citation(citation, content)
        return content[citation.start : citation.end]

    def citation_lines(
        self, inspection_ref: PoCInspectionRef, citation: SourceCitation
    ) -> tuple[int, int] | None:
        current = self._completed(inspection_ref)
        assert current.document is not None
        if citation not in current.document.citations:
            raise InspectionError("CITATION_INVALID")
        source = VerifiedSource(
            current, self._artifacts, deadline=time.monotonic() + current.limits.max_wall_seconds
        )
        content = source.verify_entry(citation.path)
        source.validate_citation(citation, content)
        return line_span(content, citation.start, citation.end)

    def recover_interrupted(self) -> tuple[PoCInspection, ...]:
        """Conservatively stop unproven INSPECTING attempts after Core restart."""

        with self._database.unit_of_work() as work:
            return tuple(
                work.inspections.update(
                    item.model_copy(
                        update={
                            "status": InspectionStatus.INTERRUPTED,
                            "finished_at": self._now(),
                            "diagnostic": "INSPECTION_INTERRUPTED",
                        }
                    )
                )
                for item in work.inspections.list_inspecting()
            )

    def _completed(self, inspection_ref: PoCInspectionRef) -> PoCInspection:
        current = self.get(inspection_ref)
        if current is None or current.status is not InspectionStatus.COMPLETED:
            raise InspectionError("INSPECTION_NOT_COMPLETED")
        return current

    def _finish(
        self,
        current: PoCInspection,
        status: InspectionStatus,
        *,
        document: InspectionDocument | SemanticInspectionDocument | None = None,
        diagnostic: str | None = None,
    ) -> PoCInspection:
        with self._database.unit_of_work() as work:
            stored = work.inspections.get(current.inspection_ref)
            if stored is None or stored.status is not InspectionStatus.INSPECTING:
                raise InspectionError("INSPECTION_STATE_CONFLICT")
            return work.inspections.update(
                stored.model_copy(
                    update={
                        "status": status,
                        "finished_at": self._now(),
                        "document": document,
                        "diagnostic": diagnostic,
                    }
                )
            )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise InspectionError("INSPECTION_CLOCK_INVALID")
        return value
