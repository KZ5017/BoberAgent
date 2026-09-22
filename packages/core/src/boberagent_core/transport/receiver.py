"""Core transport receiving boundary without Result ingestion or Event Bus behavior."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from boberagent_contracts import CapabilityRunRef, DomainRef, JsonObject
from boberagent_transport import (
    CapabilityTransport,
    DeliveryAcknowledgement,
    DeliveryKind,
    EventEnvelope,
    InvocationDelivery,
    NodeAdvertisement,
    ResultEnvelope,
    TransportMessageId,
    ensure_supported_protocol,
    parse_outbound,
)
from pydantic import TypeAdapter

from boberagent_core.clock import utc_now
from boberagent_core.interactions import CoreInteractionService
from boberagent_core.persistence.database import CoreDatabase
from boberagent_core.results import ResultIngestionService

from .models import TransportInboxRecord

_json_object_adapter: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class CoreTransportReceiver:
    """Validate and durably deduplicate delivery without changing domain state."""

    def __init__(
        self,
        database: CoreDatabase,
        *,
        clock: Callable[[], datetime] = utc_now,
        result_ingestion: ResultIngestionService | None = None,
        process_results: bool = True,
    ) -> None:
        self._database = database
        self._clock = clock
        self._result_ingestion = result_ingestion
        self._process_results = process_results

    def accept(self, serialized: bytes) -> tuple[TransportInboxRecord, DeliveryAcknowledgement]:
        envelope = parse_outbound(serialized)
        ensure_supported_protocol(envelope.protocol_version)
        if isinstance(envelope, EventEnvelope):
            kind = DeliveryKind.EVENT
            payload_id: DomainRef = envelope.event.event_id
        else:
            kind = DeliveryKind.RESULT
            payload_id = envelope.result.run_ref
        envelope_json = _json_object_adapter.validate_python(envelope.model_dump(mode="json"))
        received_at = self._clock()
        with self._database.unit_of_work() as work:
            record = work.transport_inbox.accept(
                message_id=envelope.message_id,
                node_id=envelope.node_id,
                message_kind=kind,
                correlation_id=envelope.correlation_id,
                payload_id=payload_id,
                outbox_sequence=envelope.outbox_sequence,
                envelope=envelope_json,
                received_at=received_at,
            )
        if isinstance(envelope, ResultEnvelope) and self._result_ingestion is not None:
            self._result_ingestion.accept_result(
                envelope.result,
                transport_message_id=str(envelope.message_id),
                source_node_id=envelope.node_id,
                received_at=received_at,
            )
            if self._process_results:
                self._result_ingestion.process_ingestion(envelope.result.run_ref)
        if isinstance(envelope, EventEnvelope):
            CoreInteractionService(self._database).observe_event(envelope.node_id, envelope.event)
        acknowledgement = DeliveryAcknowledgement(
            message_id=envelope.message_id,
            node_id=envelope.node_id,
            delivery_kind=kind,
            payload_id=payload_id,
            correlation_id=envelope.correlation_id,
            acknowledged_at=received_at,
        )
        return record, acknowledgement

    def records_for_run(self, run_ref: CapabilityRunRef) -> tuple[TransportInboxRecord, ...]:
        with self._database.unit_of_work() as work:
            return work.transport_inbox.list_for_run(run_ref)

    def result_for_run(self, run_ref: CapabilityRunRef) -> ResultEnvelope | None:
        for record in self.records_for_run(run_ref):
            if record.message_kind is DeliveryKind.RESULT:
                return ResultEnvelope.model_validate(record.envelope)
        return None

    def events_for_run(self, run_ref: CapabilityRunRef) -> tuple[EventEnvelope, ...]:
        return tuple(
            EventEnvelope.model_validate(record.envelope)
            for record in self.records_for_run(run_ref)
            if record.message_kind is DeliveryKind.EVENT
        )


class CoreTransportClient:
    """Explicit-node Core caller; capability routing remains a later milestone."""

    def __init__(
        self,
        transport: CapabilityTransport,
        receiver: CoreTransportReceiver,
    ) -> None:
        self._transport = transport
        self._receiver = receiver

    async def discover_node(self, node_id: str) -> NodeAdvertisement:
        return await self._transport.discover_node(node_id)

    async def submit_invocation(
        self, node_id: str, delivery: InvocationDelivery
    ) -> TransportMessageId:
        return await self._transport.submit_invocation(node_id, delivery)

    async def receive_one(self, *, acknowledge: bool = True) -> TransportInboxRecord:
        serialized = await self._transport.receive()
        record, acknowledgement = self._receiver.accept(serialized)
        if acknowledge:
            await self._transport.acknowledge(acknowledgement)
        return record

    async def flush_node(self, node_id: str) -> int:
        return await self._transport.flush_outboxes(node_id)
