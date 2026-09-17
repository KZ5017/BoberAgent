"""Persistence mapping for canonical CapabilityResult ingestion records."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from boberagent_contracts import CapabilityResult, CapabilityRunRef, JsonObject
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from boberagent_core.persistence.orm import ResultIngestionRow

from .models import ResultIngestion, ResultIngestionStatus

_json_object_adapter: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class ResultIngestionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_received(
        self,
        *,
        result: CapabilityResult,
        fingerprint: str,
        received_at: datetime,
        transport_message_id: str | None,
        source_node_id: str | None,
    ) -> ResultIngestion:
        row = ResultIngestionRow(
            run_id=str(result.run_ref),
            result_fingerprint=fingerprint,
            result_json=deepcopy(
                _json_object_adapter.validate_python(result.model_dump(mode="json"))
            ),
            transport_message_id=transport_message_id,
            source_node_id=source_node_id,
            status=ResultIngestionStatus.RECEIVED.value,
            received_at=received_at,
            updated_at=received_at,
            processing_attempts=0,
            materialized_count=0,
            unsupported_count=0,
            rejected_count=0,
            conflict_count=0,
        )
        self._session.add(row)
        self._session.flush()
        return _from_row(row)

    def get(self, run_ref: CapabilityRunRef) -> ResultIngestion | None:
        row = self._session.get(ResultIngestionRow, str(run_ref))
        return None if row is None else _from_row(row)

    def list_processable(self, *, limit: int | None = None) -> tuple[ResultIngestion, ...]:
        statement = (
            select(ResultIngestionRow)
            .where(
                ResultIngestionRow.status.in_(
                    (
                        ResultIngestionStatus.RECEIVED.value,
                        ResultIngestionStatus.PROCESSING.value,
                        ResultIngestionStatus.FAILED.value,
                    )
                )
            )
            .order_by(ResultIngestionRow.received_at, ResultIngestionRow.run_id)
        )
        if limit is not None:
            statement = statement.limit(limit)
        return tuple(_from_row(row) for row in self._session.scalars(statement))

    def record_conflict(
        self,
        run_ref: CapabilityRunRef,
        *,
        fingerprint: str,
        occurred_at: datetime,
    ) -> ResultIngestion:
        row = self._required(run_ref)
        row.conflict_count += 1
        row.last_conflict_fingerprint = fingerprint
        row.last_conflict_at = occurred_at
        row.updated_at = occurred_at
        self._session.flush()
        return _from_row(row)

    def mark_processing(self, run_ref: CapabilityRunRef, occurred_at: datetime) -> None:
        row = self._required(run_ref)
        row.status = ResultIngestionStatus.PROCESSING.value
        row.processing_attempts += 1
        row.updated_at = occurred_at
        row.error = None
        self._session.flush()

    def mark_finished(
        self,
        run_ref: CapabilityRunRef,
        *,
        status: ResultIngestionStatus,
        occurred_at: datetime,
        materialized_count: int = 0,
        unsupported_count: int = 0,
        rejected_count: int = 0,
        error: str | None = None,
    ) -> ResultIngestion:
        row = self._required(run_ref)
        row.status = status.value
        row.updated_at = occurred_at
        row.processed_at = occurred_at if status.is_complete else None
        row.materialized_count = materialized_count
        row.unsupported_count = unsupported_count
        row.rejected_count = rejected_count
        row.error = error
        self._session.flush()
        return _from_row(row)

    def _required(self, run_ref: CapabilityRunRef) -> ResultIngestionRow:
        row = self._session.get(ResultIngestionRow, str(run_ref))
        if row is None:
            raise KeyError(f"unknown Result ingestion: {run_ref}")
        return row


def _from_row(row: ResultIngestionRow) -> ResultIngestion:
    return ResultIngestion(
        run_ref=CapabilityRunRef(row.run_id),
        result_fingerprint=row.result_fingerprint,
        result=CapabilityResult.model_validate(deepcopy(row.result_json)),
        transport_message_id=row.transport_message_id,
        source_node_id=row.source_node_id,
        status=ResultIngestionStatus(row.status),
        received_at=row.received_at,
        updated_at=row.updated_at,
        processed_at=row.processed_at,
        processing_attempts=row.processing_attempts,
        materialized_count=row.materialized_count,
        unsupported_count=row.unsupported_count,
        rejected_count=row.rejected_count,
        error=row.error,
        conflict_count=row.conflict_count,
        last_conflict_fingerprint=row.last_conflict_fingerprint,
        last_conflict_at=row.last_conflict_at,
    )
