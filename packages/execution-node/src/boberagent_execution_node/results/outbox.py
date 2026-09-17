"""Persistent CapabilityResult delivery foundation."""

from datetime import datetime

from boberagent_contracts import CapabilityResult, CapabilityRunRef

from boberagent_execution_node.persistence import ResultOutboxRecord, RuntimeStore


class ResultOutbox:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def persist_terminal(
        self,
        result: CapabilityResult,
        *,
        finished_at: datetime,
        error_code: str | None = None,
    ) -> None:
        self._store.enqueue_result_and_finish_run(
            result, finished_at=finished_at, error_code=error_code
        )

    def get(self, run_ref: CapabilityRunRef) -> CapabilityResult | None:
        return self._store.get_result(run_ref)

    def pending(self) -> tuple[ResultOutboxRecord, ...]:
        return self._store.pending_results()

    def mark_delivered(self, sequence: int) -> None:
        self._store.mark_result_delivered(sequence)
