"""Node-owned probe journal; paths/PIDs are never persisted as authority."""

from datetime import datetime

from boberagent_contracts import DomainRef
from boberagent_contracts.python_runtime import RuntimeCorrelation
from sqlalchemy import select, text

from ..persistence.database import RuntimeDatabase
from ..persistence.orm import RuntimeConfinementRow
from .runtime_confinement_models import (
    ClosedProbe,
    ProbeEvidence,
    ProbeLimits,
    TrustedPythonOperation,
)


class ConfinementJournal:
    def __init__(self, database: RuntimeDatabase) -> None:
        self._database = database

    def begin(
        self,
        operation_id: RuntimeCorrelation,
        probe: ClosedProbe | TrustedPythonOperation,
        limits: ProbeLimits,
        boot: RuntimeCorrelation,
        host_boot: str,
        parent_sha256: str,
        now: datetime,
        input_sha256: str | None = None,
    ) -> ProbeEvidence | None:
        with self._database.transaction() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = session.get(RuntimeConfinementRow, str(operation_id))
            if row is not None:
                if (
                    row.probe != probe.value
                    or row.limits_json != limits.model_dump(mode="json")
                    or row.parent_sha256 != parent_sha256
                    or row.input_sha256 != input_sha256
                ):
                    raise ValueError("conflicting confinement operation identity")
                if row.evidence_json is not None:
                    return ProbeEvidence.model_validate(row.evidence_json)
                raise ValueError("operation already owned/interrupted; never replay")
            session.add(
                RuntimeConfinementRow(
                    operation_id=str(operation_id),
                    probe=probe.value,
                    limits_json=limits.model_dump(mode="json"),
                    boot_generation=str(boot),
                    host_boot=host_boot,
                    parent_sha256=parent_sha256,
                    input_sha256=input_sha256,
                    state="RUNNING",
                    started_at=now,
                    finished_at=None,
                    evidence_json=None,
                )
            )
        return None

    def finish(self, evidence: ProbeEvidence, now: datetime) -> None:
        with self._database.transaction() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = session.get(RuntimeConfinementRow, str(evidence.operation_id))
            if row is None or row.state != "RUNNING":
                raise ValueError("missing active confinement ownership")
            row.state = "FINISHED"
            row.finished_at = now
            row.evidence_json = evidence.model_dump(mode="json")

    def interrupt(self, operation_id: RuntimeCorrelation, now: datetime) -> None:
        with self._database.transaction() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            row = session.get(RuntimeConfinementRow, str(operation_id))
            if row is not None and row.state == "RUNNING":
                row.state = "INTERRUPTED"
                row.finished_at = now

    def pending(self) -> tuple[tuple[RuntimeCorrelation, str, str], ...]:
        with self._database.transaction() as session:
            return tuple(
                (DomainRef(row.operation_id), row.host_boot, row.parent_sha256)
                for row in session.scalars(
                    select(RuntimeConfinementRow).where(RuntimeConfinementRow.state == "RUNNING")
                )
            )
