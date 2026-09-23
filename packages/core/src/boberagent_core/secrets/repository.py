"""Private persistence repository for canonical Secret values and access audit metadata."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from boberagent_contracts import (
    ArtifactRef,
    CapabilityRunRef,
    MissionRef,
    ObservationRef,
    SecretRef,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from boberagent_core.models import SecretAccessRecord, SecretMetadata, SecretStatus
from boberagent_core.persistence.orm import SecretAccessRow, SecretRow
from boberagent_core.persistence.repositories import _flush_identity


class SecretRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, metadata: SecretMetadata, value: bytes) -> None:
        self._session.add(
            SecretRow(
                secret_id=str(metadata.secret_ref),
                mission_id=str(metadata.mission_ref),
                secret_type=metadata.secret_type,
                value_blob=bytes(value),
                status=metadata.status.value,
                created_at=metadata.created_at,
                created_by_run_id=(
                    None
                    if metadata.created_by_run_ref is None
                    else str(metadata.created_by_run_ref)
                ),
                source_observation_id=(
                    None
                    if metadata.source_observation_ref is None
                    else str(metadata.source_observation_ref)
                ),
                source_artifact_refs_json=[str(ref) for ref in metadata.source_artifact_refs],
                metadata_json=deepcopy(metadata.metadata),
            )
        )
        _flush_identity(self._session, metadata.secret_ref)

    def get(self, secret_ref: SecretRef) -> SecretMetadata | None:
        row = self._session.get(SecretRow, str(secret_ref))
        return None if row is None else _metadata_from_row(row)

    def value(self, secret_ref: SecretRef) -> bytes | None:
        row = self._session.get(SecretRow, str(secret_ref))
        return None if row is None else bytes(row.value_blob)

    def list_for_mission(self, mission_ref: MissionRef) -> tuple[SecretMetadata, ...]:
        rows = self._session.scalars(
            select(SecretRow)
            .where(SecretRow.mission_id == str(mission_ref))
            .order_by(SecretRow.secret_id)
        )
        return tuple(_metadata_from_row(row) for row in rows)

    def set_status(self, secret_ref: SecretRef, status: SecretStatus) -> SecretMetadata:
        row = self._session.get(SecretRow, str(secret_ref))
        if row is None:
            raise KeyError(f"unknown Secret: {secret_ref}")
        row.status = status.value
        self._session.flush()
        return _metadata_from_row(row)

    def record_access(
        self,
        *,
        secret_ref: SecretRef,
        mission_ref: MissionRef,
        run_ref: CapabilityRunRef | None,
        accessor: str,
        purpose: str,
        accessed_at: datetime,
    ) -> SecretAccessRecord:
        row = SecretAccessRow(
            secret_id=str(secret_ref),
            mission_id=str(mission_ref),
            run_id=None if run_ref is None else str(run_ref),
            accessor=accessor,
            purpose=purpose,
            accessed_at=accessed_at,
        )
        self._session.add(row)
        self._session.flush()
        return _access_from_row(row)

    def list_access(self, secret_ref: SecretRef) -> tuple[SecretAccessRecord, ...]:
        rows = self._session.scalars(
            select(SecretAccessRow)
            .where(SecretAccessRow.secret_id == str(secret_ref))
            .order_by(SecretAccessRow.access_id)
        )
        return tuple(_access_from_row(row) for row in rows)


def _metadata_from_row(row: SecretRow) -> SecretMetadata:
    return SecretMetadata(
        secret_ref=SecretRef(row.secret_id),
        mission_ref=MissionRef(row.mission_id),
        secret_type=row.secret_type,
        status=SecretStatus(row.status),
        created_at=row.created_at,
        created_by_run_ref=(
            None if row.created_by_run_id is None else CapabilityRunRef(row.created_by_run_id)
        ),
        source_observation_ref=(
            None if row.source_observation_id is None else ObservationRef(row.source_observation_id)
        ),
        source_artifact_refs=tuple(ArtifactRef(ref) for ref in row.source_artifact_refs_json),
        metadata=deepcopy(row.metadata_json),
    )


def _access_from_row(row: SecretAccessRow) -> SecretAccessRecord:
    return SecretAccessRecord(
        access_id=row.access_id,
        secret_ref=SecretRef(row.secret_id),
        mission_ref=MissionRef(row.mission_id),
        run_ref=None if row.run_id is None else CapabilityRunRef(row.run_id),
        accessor=row.accessor,
        purpose=row.purpose,
        accessed_at=row.accessed_at,
    )
