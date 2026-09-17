"""Explicit repository for Core transport inbox deduplication metadata."""

from copy import deepcopy
from datetime import datetime

from boberagent_contracts import CapabilityRunRef, DomainRef, JsonObject
from boberagent_transport import DeliveryKind, TransportMessageId
from sqlalchemy import select
from sqlalchemy.orm import Session

from boberagent_core.persistence.orm import TransportInboxRow
from boberagent_core.persistence.repositories import PersistenceIntegrityError

from .models import TransportInboxRecord


class TransportInboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def accept(
        self,
        *,
        message_id: TransportMessageId,
        node_id: str,
        message_kind: DeliveryKind,
        correlation_id: CapabilityRunRef,
        payload_id: DomainRef,
        outbox_sequence: int,
        envelope: JsonObject,
        received_at: datetime,
    ) -> TransportInboxRecord:
        row = self._session.get(TransportInboxRow, str(message_id))
        if row is not None:
            if (
                row.node_id != node_id
                or row.message_kind != message_kind.value
                or row.correlation_id != str(correlation_id)
                or row.payload_id != str(payload_id)
                or row.outbox_sequence != outbox_sequence
                or row.envelope_json != envelope
            ):
                raise PersistenceIntegrityError(
                    f"transport message identity collision: {message_id}"
                )
            row.delivery_count += 1
            self._session.flush()
            return _record(row)

        row = TransportInboxRow(
            message_id=str(message_id),
            node_id=node_id,
            message_kind=message_kind.value,
            correlation_id=str(correlation_id),
            payload_id=str(payload_id),
            outbox_sequence=outbox_sequence,
            envelope_json=deepcopy(envelope),
            received_at=received_at,
            delivery_count=1,
        )
        self._session.add(row)
        self._session.flush()
        return _record(row)

    def get(self, message_id: TransportMessageId) -> TransportInboxRecord | None:
        row = self._session.get(TransportInboxRow, str(message_id))
        return None if row is None else _record(row)

    def list_for_run(self, run_ref: CapabilityRunRef) -> tuple[TransportInboxRecord, ...]:
        rows = self._session.scalars(
            select(TransportInboxRow)
            .where(TransportInboxRow.correlation_id == str(run_ref))
            .order_by(TransportInboxRow.received_at, TransportInboxRow.message_id)
        )
        return tuple(_record(row) for row in rows)


def _record(row: TransportInboxRow) -> TransportInboxRecord:
    return TransportInboxRecord(
        message_id=TransportMessageId(row.message_id),
        node_id=row.node_id,
        message_kind=DeliveryKind(row.message_kind),
        correlation_id=CapabilityRunRef(row.correlation_id),
        payload_id=DomainRef(row.payload_id),
        outbox_sequence=row.outbox_sequence,
        envelope=deepcopy(row.envelope_json),
        received_at=row.received_at,
        delivery_count=row.delivery_count,
    )
