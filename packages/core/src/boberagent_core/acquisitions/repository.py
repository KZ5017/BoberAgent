"""Core-only acquisition persistence; caller controls the transaction."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from boberagent_contracts import CapabilityRunRef, MissionRef, PoCAcquisitionRef
from boberagent_contracts.poc_acquisition import (
    PoCAcquisitionBounds,
    PoCSourceAcquisitionReceipt,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from boberagent_core.persistence.orm import PoCAcquisitionRow
from boberagent_core.research.models import (
    PoCCandidateRef,
    ResearchAttemptRef,
    VulnerabilityHypothesisRef,
)

from .models import PoCAcquisition, PoCAcquisitionStatus

_NEXT: dict[PoCAcquisitionStatus, frozenset[PoCAcquisitionStatus]] = {
    PoCAcquisitionStatus.REQUESTED: frozenset(
        {
            PoCAcquisitionStatus.DISPATCHED,
            PoCAcquisitionStatus.FAILED,
            PoCAcquisitionStatus.REJECTED,
            PoCAcquisitionStatus.INTERRUPTED,
        }
    ),
    PoCAcquisitionStatus.DISPATCHED: frozenset(
        {
            PoCAcquisitionStatus.AWAITING_ARTIFACT,
            PoCAcquisitionStatus.FAILED,
            PoCAcquisitionStatus.REJECTED,
            PoCAcquisitionStatus.INTERRUPTED,
        }
    ),
    PoCAcquisitionStatus.AWAITING_ARTIFACT: frozenset(
        {
            PoCAcquisitionStatus.COMPLETED,
            PoCAcquisitionStatus.FAILED,
            PoCAcquisitionStatus.REJECTED,
            PoCAcquisitionStatus.INTERRUPTED,
        }
    ),
}


class PoCAcquisitionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, acquisition: PoCAcquisition) -> None:
        self._session.add(
            PoCAcquisitionRow(
                acquisition_id=str(acquisition.acquisition_ref),
                mission_id=str(acquisition.mission_ref),
                hypothesis_id=str(acquisition.hypothesis_ref),
                candidate_id=str(acquisition.candidate_ref),
                selected_hit_id=acquisition.selected_hit_id,
                research_attempt_id=str(acquisition.research_attempt_ref),
                research_provider_id=acquisition.research_provider_id,
                source_identity=acquisition.source_identity,
                source_uri=acquisition.source_uri,
                repository_uri=acquisition.repository_uri,
                provider_repository_id=acquisition.provider_repository_id,
                historical_ref=acquisition.historical_ref,
                bounds_json=acquisition.bounds.model_dump(mode="json"),
                status=acquisition.status.value,
                created_at=acquisition.created_at,
                updated_at=acquisition.updated_at,
            )
        )
        self._session.flush()

    def get(self, acquisition_ref: PoCAcquisitionRef) -> PoCAcquisition | None:
        row = self._session.get(PoCAcquisitionRow, str(acquisition_ref))
        return None if row is None else _from_row(row)

    def list_for_candidate(self, candidate_ref: PoCCandidateRef) -> tuple[PoCAcquisition, ...]:
        rows = self._session.scalars(
            select(PoCAcquisitionRow)
            .where(PoCAcquisitionRow.candidate_id == str(candidate_ref))
            .order_by(PoCAcquisitionRow.created_at, PoCAcquisitionRow.acquisition_id)
        )
        return tuple(_from_row(row) for row in rows)

    def get_by_run(self, run_ref: CapabilityRunRef) -> PoCAcquisition | None:
        row = self._session.scalar(
            select(PoCAcquisitionRow).where(PoCAcquisitionRow.run_id == str(run_ref))
        )
        return None if row is None else _from_row(row)

    def update(self, acquisition: PoCAcquisition) -> PoCAcquisition:
        row = self._session.get(PoCAcquisitionRow, str(acquisition.acquisition_ref))
        if row is None:
            raise KeyError("unknown PoCAcquisition")
        old = _from_row(row)
        if old == acquisition:
            return old
        if acquisition.status not in _NEXT.get(old.status, frozenset()):
            raise ValueError(
                f"illegal PoCAcquisition transition: {old.status} → {acquisition.status}"
            )
        if (
            old.mission_ref != acquisition.mission_ref
            or old.hypothesis_ref != acquisition.hypothesis_ref
            or old.candidate_ref != acquisition.candidate_ref
            or old.selected_hit_id != acquisition.selected_hit_id
            or old.research_attempt_ref != acquisition.research_attempt_ref
            or old.research_provider_id != acquisition.research_provider_id
            or old.created_at != acquisition.created_at
            or old.source_identity != acquisition.source_identity
            or old.source_uri != acquisition.source_uri
            or old.repository_uri != acquisition.repository_uri
            or old.provider_repository_id != acquisition.provider_repository_id
            or old.historical_ref != acquisition.historical_ref
            or old.bounds != acquisition.bounds
            or (old.run_ref is not None and old.run_ref != acquisition.run_ref)
            or (
                old.routing_provider_id is not None
                and old.routing_provider_id != acquisition.routing_provider_id
            )
            or (old.node_id is not None and old.node_id != acquisition.node_id)
            or (old.receipt is not None and old.receipt != acquisition.receipt)
        ):
            raise ValueError("immutable PoCAcquisition identity or provenance changed")
        row.status = acquisition.status.value
        row.run_id = None if acquisition.run_ref is None else str(acquisition.run_ref)
        row.routing_provider_id = (
            None
            if acquisition.routing_provider_id is None
            else str(acquisition.routing_provider_id)
        )
        row.node_id = acquisition.node_id
        row.receipt_json = (
            None
            if acquisition.receipt is None
            else deepcopy(acquisition.receipt.model_dump(mode="json"))
        )
        receipt = acquisition.receipt
        if receipt is not None:
            row.resolved_commit_sha = receipt.resolved_commit_sha
            row.raw_artifact_id = str(receipt.raw_source.artifact_id)
            row.raw_archive_sha256 = receipt.raw_archive_sha256
            row.raw_archive_size_bytes = receipt.raw_archive_size_bytes
            row.manifest_artifact_id = str(receipt.manifest.artifact_id)
            row.manifest_sha256 = receipt.manifest_sha256
            row.adapter_id = receipt.adapter_id
            row.adapter_version = receipt.adapter_version
        row.updated_at = acquisition.updated_at
        row.diagnostic = acquisition.diagnostic
        self._session.flush()
        return _from_row(row)


def _from_row(row: PoCAcquisitionRow) -> PoCAcquisition:
    return PoCAcquisition(
        acquisition_ref=PoCAcquisitionRef(row.acquisition_id),
        mission_ref=MissionRef(row.mission_id),
        hypothesis_ref=VulnerabilityHypothesisRef(row.hypothesis_id),
        candidate_ref=PoCCandidateRef(row.candidate_id),
        selected_hit_id=row.selected_hit_id,
        research_attempt_ref=ResearchAttemptRef(row.research_attempt_id),
        research_provider_id=row.research_provider_id,
        source_identity=row.source_identity,
        source_uri=row.source_uri,
        repository_uri=row.repository_uri,
        provider_repository_id=row.provider_repository_id,
        historical_ref=row.historical_ref,
        bounds=PoCAcquisitionBounds.model_validate(deepcopy(row.bounds_json)),
        status=PoCAcquisitionStatus(row.status),
        run_ref=None if row.run_id is None else CapabilityRunRef(row.run_id),
        routing_provider_id=(
            None if row.routing_provider_id is None else UUID(row.routing_provider_id)
        ),
        node_id=row.node_id,
        receipt=(
            None
            if row.receipt_json is None
            else PoCSourceAcquisitionReceipt.model_validate(deepcopy(row.receipt_json))
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
        diagnostic=row.diagnostic,
    )
