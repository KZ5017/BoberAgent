"""Core-owned durable E3 transfer cursor; never stores imported bytes."""

from datetime import datetime
from enum import StrEnum

from boberagent_contracts import ArtifactRef, RuntimePreparationRef, Sha256Digest
from boberagent_contracts._base import FrozenContractModel
from boberagent_transport import PreparationImportId
from pydantic import AwareDatetime, Field
from sqlalchemy.orm import Session

from boberagent_core.persistence.preparation_orm import PreparationImportProgressRow


class ImportProgressState(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class PreparationImportProgress(FrozenContractModel):
    import_id: PreparationImportId
    preparation_ref: RuntimePreparationRef
    artifact_ref: ArtifactRef
    sha256: Sha256Digest
    size_bytes: int = Field(ge=0)
    received_bytes: int = Field(ge=0)
    state: ImportProgressState
    updated_at: AwareDatetime
    error_code: str | None = None


class PreparationImportProgressRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, import_id: PreparationImportId) -> PreparationImportProgress | None:
        row = self._session.get(PreparationImportProgressRow, str(import_id))
        return None if row is None else _load(row)

    def record(
        self,
        *,
        import_id: PreparationImportId,
        preparation_ref: RuntimePreparationRef,
        artifact_ref: ArtifactRef,
        sha256: str,
        size_bytes: int,
        received_bytes: int,
        state: ImportProgressState,
        updated_at: datetime,
        error_code: str | None = None,
    ) -> PreparationImportProgress:
        if size_bytes < 0 or not 0 <= received_bytes <= size_bytes:
            raise ValueError("import progress exceeds exact Artifact size")
        row = self._session.get(PreparationImportProgressRow, str(import_id))
        if row is None:
            row = PreparationImportProgressRow(
                import_id=str(import_id),
                preparation_id=str(preparation_ref),
                artifact_id=str(artifact_ref),
                sha256=sha256,
                size_bytes=size_bytes,
                received_bytes=received_bytes,
                state=state.value,
                updated_at=updated_at,
                error_code=error_code,
            )
            self._session.add(row)
        else:
            if (
                row.preparation_id != str(preparation_ref)
                or row.artifact_id != str(artifact_ref)
                or row.sha256 != sha256
                or row.size_bytes != size_bytes
            ):
                raise ValueError("import identity conflicts with persisted Core progress")
            if row.state == ImportProgressState.VERIFIED.value:
                if state is not ImportProgressState.VERIFIED:
                    raise ValueError("verified import cannot be reopened")
                return _load(row)
            if received_bytes < row.received_bytes and state is not ImportProgressState.FAILED:
                raise ValueError("import progress cannot regress")
            row.received_bytes = received_bytes
            row.state = state.value
            row.updated_at = updated_at
            row.error_code = error_code
        self._session.flush()
        return _load(row)


def _load(row: PreparationImportProgressRow) -> PreparationImportProgress:
    return PreparationImportProgress(
        import_id=PreparationImportId(row.import_id),
        preparation_ref=RuntimePreparationRef(row.preparation_id),
        artifact_ref=ArtifactRef(row.artifact_id),
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        received_bytes=row.received_bytes,
        state=ImportProgressState(row.state),
        updated_at=row.updated_at,
        error_code=row.error_code,
    )
