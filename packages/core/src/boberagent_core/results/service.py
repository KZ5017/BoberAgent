"""Durable, restart-safe CapabilityResult semantic ingestion."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime

from boberagent_contracts import CapabilityResult, CapabilityRunRef

from boberagent_core.clock import utc_now
from boberagent_core.models import MaterializationStatus
from boberagent_core.persistence import CoreDatabase, PersistenceIntegrityError
from boberagent_core.state import ReducerRegistry

from .errors import ConflictingResultError, ResultProvenanceError
from .models import ResultIngestion, ResultIngestionStatus


class ResultIngestionService:
    """Persist the complete Result before transactionally applying understood semantics."""

    def __init__(
        self,
        database: CoreDatabase,
        *,
        reducers: ReducerRegistry | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._database = database
        self._reducers = reducers or ReducerRegistry()
        self._clock = clock

    def accept_result(
        self,
        result: CapabilityResult,
        *,
        transport_message_id: str | None = None,
        source_node_id: str | None = None,
        received_at: datetime | None = None,
    ) -> ResultIngestion:
        """Durably record one canonical Result without materializing it yet."""

        validated = CapabilityResult.model_validate(result.model_dump(mode="python"))
        fingerprint = result_fingerprint(validated)
        occurred_at = received_at or self._clock()
        _require_aware(occurred_at)
        conflict = False
        with self._database.unit_of_work() as work:
            existing = work.result_ingestions.get(validated.run_ref)
            if existing is None:
                return work.result_ingestions.add_received(
                    result=validated,
                    fingerprint=fingerprint,
                    received_at=occurred_at,
                    transport_message_id=transport_message_id,
                    source_node_id=source_node_id,
                )
            if existing.result_fingerprint != fingerprint:
                work.result_ingestions.record_conflict(
                    validated.run_ref,
                    fingerprint=fingerprint,
                    occurred_at=occurred_at,
                )
                conflict = True
            else:
                return existing
        if conflict:
            raise ConflictingResultError(
                f"CapabilityRun has a different canonical Result: {validated.run_ref}"
            )
        raise AssertionError("unreachable Result acceptance state")

    def process_ingestion(self, run_ref: CapabilityRunRef) -> ResultIngestion:
        """Apply one durable Result; safe to call again after interruption."""

        with self._database.unit_of_work() as work:
            ingestion = work.result_ingestions.get(run_ref)
            if ingestion is None:
                raise KeyError(f"unknown Result ingestion: {run_ref}")
            if ingestion.status.is_complete:
                return ingestion
            work.result_ingestions.mark_processing(run_ref, self._now())

        try:
            return self._process_transaction(run_ref)
        except (PersistenceIntegrityError, ResultProvenanceError, KeyError) as error:
            return self._mark_failure(
                run_ref,
                ResultIngestionStatus.REJECTED,
                str(error),
            )
        except Exception as error:
            return self._mark_failure(
                run_ref,
                ResultIngestionStatus.FAILED,
                f"{type(error).__name__}: {error}",
            )

    def process_pending(self, *, limit: int | None = None) -> tuple[ResultIngestion, ...]:
        """Recover receipt/processing/local-failure records after restart."""

        with self._database.unit_of_work() as work:
            pending = work.result_ingestions.list_processable(limit=limit)
        return tuple(self.process_ingestion(record.run_ref) for record in pending)

    def get_ingestion(self, run_ref: CapabilityRunRef) -> ResultIngestion | None:
        with self._database.unit_of_work() as work:
            return work.result_ingestions.get(run_ref)

    def _process_transaction(self, run_ref: CapabilityRunRef) -> ResultIngestion:
        occurred_at = self._now()
        with self._database.unit_of_work() as work:
            ingestion = work.result_ingestions.get(run_ref)
            if ingestion is None:
                raise KeyError(f"unknown Result ingestion: {run_ref}")
            result = ingestion.result
            run = work.runs.get(run_ref)
            if run is None:
                raise ResultProvenanceError(
                    f"Result references unknown CapabilityRun; Core will not fabricate it: {run_ref}"
                )
            decision = work.routing_decisions.get(run_ref)
            if decision is not None:
                if (
                    run.capability_id != decision.capability_id
                    or run.operation != decision.operation
                ):
                    raise ResultProvenanceError(
                        f"CapabilityRun metadata conflicts with routing provenance: {run_ref}"
                    )
                if (
                    ingestion.source_node_id is not None
                    and ingestion.source_node_id != decision.node_id
                ):
                    raise ResultProvenanceError(
                        f"Result source Node conflicts with routing provenance: {run_ref}"
                    )
            _validate_result_provenance(result)
            work.runs.reconcile_terminal(
                run_ref,
                result.execution_status,
                finished_at=ingestion.received_at,
            )
            for artifact in result.artifacts:
                work.artifacts.reconcile(artifact)

            materialized = 0
            unsupported = 0
            rejected = 0
            for observation in result.observations:
                work.observations.reconcile(observation)
                status = self._reducers.materialize(observation.observation_id, work)
                if status is MaterializationStatus.MATERIALIZED:
                    materialized += 1
                elif status is MaterializationStatus.UNSUPPORTED:
                    unsupported += 1
                elif status is MaterializationStatus.REJECTED:
                    rejected += 1

            final_status = (
                ResultIngestionStatus.PARTIALLY_PROCESSED
                if unsupported or rejected
                else ResultIngestionStatus.PROCESSED
            )
            details: list[str] = []
            if unsupported:
                details.append(f"{unsupported} unsupported Observation(s)")
            if rejected:
                details.append(f"{rejected} rejected Observation(s)")
            return work.result_ingestions.mark_finished(
                run_ref,
                status=final_status,
                occurred_at=occurred_at,
                materialized_count=materialized,
                unsupported_count=unsupported,
                rejected_count=rejected,
                error="; ".join(details) or None,
            )

    def _mark_failure(
        self,
        run_ref: CapabilityRunRef,
        status: ResultIngestionStatus,
        error: str,
    ) -> ResultIngestion:
        with self._database.unit_of_work() as work:
            return work.result_ingestions.mark_finished(
                run_ref,
                status=status,
                occurred_at=self._now(),
                error=error,
            )

    def _now(self) -> datetime:
        value = self._clock()
        _require_aware(value)
        return value


def result_fingerprint(result: CapabilityResult) -> str:
    """Hash canonical JSON content, independent of transport message identity."""

    canonical = json.dumps(
        result.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_result_provenance(result: CapabilityResult) -> None:
    run_ref = result.run_ref
    producers = (
        *(observation.run_ref for observation in result.observations),
        *(finding.run_ref for finding in result.findings),
        *(artifact.created_by_run for artifact in result.artifacts),
        *(resource.created_by_run for resource in result.resources),
        *(session.created_by_run for session in result.sessions),
        *(effect.run_ref for effect in result.effects),
        *(
            diagnostic.run_ref
            for diagnostic in result.diagnostics
            if diagnostic.run_ref is not None
        ),
    )
    if any(producer != run_ref for producer in producers):
        raise ResultProvenanceError(
            f"Result contains objects produced by a different CapabilityRun: {run_ref}"
        )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Result ingestion timestamps must be timezone-aware")
