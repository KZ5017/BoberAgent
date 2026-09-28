"""Core-only inspection persistence with explicit immutable identity and transitions."""

from __future__ import annotations

from copy import deepcopy

from boberagent_contracts import ArtifactRef, MissionRef, PoCAcquisitionRef
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from boberagent_core.persistence.orm import PoCInspectionRow
from boberagent_core.research.models import PoCCandidateRef, VulnerabilityHypothesisRef

from .classification_models import ClassificationInspectionLimits, SupportClassificationDocument
from .models import (
    InspectionDocument,
    InspectionLimits,
    InspectionStatus,
    PoCInspection,
    PoCInspectionRef,
)
from .semantic_models import SemanticInspectionDocument, SemanticInspectionLimits

_NEXT = {
    InspectionStatus.REQUESTED: {InspectionStatus.INSPECTING},
    InspectionStatus.INSPECTING: {
        InspectionStatus.COMPLETED,
        InspectionStatus.FAILED,
        InspectionStatus.INTERRUPTED,
    },
}


class PoCInspectionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, inspection: PoCInspection) -> None:
        self._session.add(_to_row(inspection))
        self._session.flush()

    def get(self, inspection_ref: PoCInspectionRef) -> PoCInspection | None:
        row = self._session.get(PoCInspectionRow, str(inspection_ref))
        return None if row is None else _from_row(row)

    def list_for_acquisition(self, acquisition_ref: PoCAcquisitionRef) -> tuple[PoCInspection, ...]:
        rows = self._session.scalars(
            select(PoCInspectionRow)
            .where(PoCInspectionRow.acquisition_id == str(acquisition_ref))
            .order_by(PoCInspectionRow.created_at, PoCInspectionRow.inspection_id)
        )
        return tuple(_from_row(row) for row in rows)

    def list_inspecting(self) -> tuple[PoCInspection, ...]:
        rows = self._session.scalars(
            select(PoCInspectionRow).where(PoCInspectionRow.status == InspectionStatus.INSPECTING)
        )
        return tuple(_from_row(row) for row in rows)

    def update(self, inspection: PoCInspection) -> PoCInspection:
        row = self._session.get(PoCInspectionRow, str(inspection.inspection_ref))
        if row is None:
            raise KeyError("unknown PoCInspection")
        old = _from_row(row)
        if old == inspection:
            return old
        if inspection.status not in _NEXT.get(old.status, set()):
            raise ValueError("illegal PoCInspection transition")
        if old.model_dump(
            exclude={"status", "started_at", "finished_at", "document", "diagnostic"}
        ) != inspection.model_dump(
            exclude={"status", "started_at", "finished_at", "document", "diagnostic"}
        ) or (old.started_at is not None and old.started_at != inspection.started_at):
            raise ValueError("immutable PoCInspection identity or configuration changed")
        row.status = inspection.status.value
        row.started_at = inspection.started_at
        row.finished_at = inspection.finished_at
        row.document_json = (
            None
            if inspection.document is None
            else deepcopy(inspection.document.model_dump(mode="json"))
        )
        row.diagnostic = inspection.diagnostic
        self._session.flush()
        return _from_row(row)


def _to_row(value: PoCInspection) -> PoCInspectionRow:
    return PoCInspectionRow(
        inspection_id=str(value.inspection_ref),
        mission_id=str(value.mission_ref),
        hypothesis_id=str(value.hypothesis_ref),
        candidate_id=str(value.candidate_ref),
        acquisition_id=str(value.acquisition_ref),
        raw_artifact_id=str(value.raw_artifact_ref),
        raw_sha256=value.raw_sha256,
        raw_size_bytes=value.raw_size_bytes,
        manifest_artifact_id=str(value.manifest_artifact_ref),
        manifest_sha256=value.manifest_sha256,
        resolved_commit_sha=value.resolved_commit_sha,
        profile_id=value.profile_id,
        profile_version=value.profile_version,
        config_fingerprint=value.config_fingerprint,
        limits_json=value.limits.model_dump(mode="json"),
        selected_paths_json=list(value.selected_paths),
        status=value.status.value,
        created_at=value.created_at,
        started_at=value.started_at,
        finished_at=value.finished_at,
        document_json=(None if value.document is None else value.document.model_dump(mode="json")),
        diagnostic=value.diagnostic,
    )


def _from_row(row: PoCInspectionRow) -> PoCInspection:
    return PoCInspection(
        inspection_ref=PoCInspectionRef(row.inspection_id),
        mission_ref=MissionRef(row.mission_id),
        hypothesis_ref=VulnerabilityHypothesisRef(row.hypothesis_id),
        candidate_ref=PoCCandidateRef(row.candidate_id),
        acquisition_ref=PoCAcquisitionRef(row.acquisition_id),
        raw_artifact_ref=ArtifactRef(row.raw_artifact_id),
        raw_sha256=row.raw_sha256,
        raw_size_bytes=row.raw_size_bytes,
        manifest_artifact_ref=ArtifactRef(row.manifest_artifact_id),
        manifest_sha256=row.manifest_sha256,
        resolved_commit_sha=row.resolved_commit_sha,
        profile_id=row.profile_id,
        profile_version=row.profile_version,
        config_fingerprint=row.config_fingerprint,
        limits=TypeAdapter(
            InspectionLimits | SemanticInspectionLimits | ClassificationInspectionLimits
        ).validate_python(deepcopy(row.limits_json)),
        selected_paths=tuple(row.selected_paths_json),
        status=InspectionStatus(row.status),
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        document=(
            None
            if row.document_json is None
            else (
                SupportClassificationDocument
                if row.document_json.get("document_version")
                in {"m20-c3-support-classifier-v1", "m20-c3-support-classifier-v2"}
                else SemanticInspectionDocument
                if row.document_json.get("document_version")
                in {"m20-c2-deterministic-v1", "m20-c2-deterministic-v2"}
                else InspectionDocument
            ).model_validate(deepcopy(row.document_json))
        ),
        diagnostic=row.diagnostic,
    )
