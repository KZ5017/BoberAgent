"""Core durable interaction projection, response intent, retry, and restart tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from boberagent_contracts import (
    CapabilityRunRef,
    Event,
    EventRef,
    InteractionLifecycle,
    InteractionRef,
    InteractionRequest,
    InteractionResponse,
    InteractionType,
    JsonObject,
    MissionRef,
)
from boberagent_core import (
    CoreDatabase,
    CoreInteractionService,
    CoreTransportReceiver,
    DatabaseConfig,
    InteractionConflict,
    upgrade_database,
)
from boberagent_transport import (
    EventEnvelope,
    InteractionResponseAcknowledgement,
    TransportDisconnected,
    TransportMessageId,
    event_message_id,
    serialize_message,
)

NOW = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
REQUEST = InteractionRequest(
    interaction_id=InteractionRef("interaction-core-restart"),
    run_ref=CapabilityRunRef("run-core-restart"),
    mission_ref=MissionRef("mission-core-restart"),
    interaction_type=InteractionType.TEXT,
    title="Parameter",
    description="Provide a harmless bounded identifier.",
    input_schema={"type": "string", "minLength": 1, "maxLength": 32},
    resume_semantics="same_run",
    requested_at=NOW,
)


class RecordingInteractionTransport:
    def __init__(self) -> None:
        self.responses: list[InteractionResponse] = []
        self.fail_once = False

    async def submit_interaction_response(
        self, node_id: str, response: InteractionResponse
    ) -> InteractionResponseAcknowledgement:
        assert node_id == "node-interaction"
        self.responses.append(response)
        if self.fail_once:
            self.fail_once = False
            raise TransportDisconnected("simulated lost acknowledgement")
        return InteractionResponseAcknowledgement(
            request_message_id=TransportMessageId(
                f"transport-interaction-response:{response.interaction_ref}"
            ),
            node_id=node_id,
            correlation_id=response.run_ref,
            interaction_ref=response.interaction_ref,
            accepted_at=response.responded_at + timedelta(milliseconds=1),
            duplicate=len(self.responses) > 1,
        )


def _database(path: Path) -> CoreDatabase:
    database = CoreDatabase(DatabaseConfig.sqlite(path))
    upgrade_database(database)
    return database


def _event_message(event_type: str = "interaction.requested") -> bytes:
    payload: JsonObject = (
        {"interaction_ref": str(REQUEST.interaction_id), "request": REQUEST.model_dump(mode="json")}
        if event_type == "interaction.requested"
        else {"interaction_ref": str(REQUEST.interaction_id), "reason": "Node restart"}
    )
    event = Event(
        event_id=EventRef(f"event-{event_type}"),
        type=event_type,
        timestamp=NOW,
        mission_ref=REQUEST.mission_ref,
        source_ref=REQUEST.run_ref,
        payload=payload,
    )
    return serialize_message(
        EventEnvelope(
            message_id=event_message_id(event.event_id),
            node_id="node-interaction",
            correlation_id=REQUEST.run_ref,
            timestamp=NOW,
            outbox_sequence=1,
            event=event,
        )
    )


def test_core_projects_request_and_preserves_it_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "core.sqlite3"
    first = _database(path)
    try:
        CoreTransportReceiver(first).accept(_event_message())
        pending = CoreInteractionService(first).list_pending()
        assert len(pending) == 1
        assert pending[0].request == REQUEST
        assert pending[0].state is InteractionLifecycle.REQUESTED
    finally:
        first.dispose()

    reopened = _database(path)
    try:
        restored = CoreInteractionService(reopened).get(REQUEST.interaction_id)
        assert restored is not None and restored.request == REQUEST
        CoreTransportReceiver(reopened).accept(_event_message())
        assert len(CoreInteractionService(reopened).list_all()) == 1
    finally:
        reopened.dispose()


def test_response_intent_survives_lost_ack_and_conflict_is_rejected(tmp_path: Path) -> None:
    database = _database(tmp_path / "core.sqlite3")
    CoreTransportReceiver(database).accept(_event_message())
    transport = RecordingInteractionTransport()
    service = CoreInteractionService(database, transport, clock=lambda: NOW + timedelta(seconds=1))
    transport.fail_once = True

    async def scenario() -> None:
        with pytest.raises(TransportDisconnected):
            await service.respond(REQUEST.interaction_id, "host-parameter")
        persisted = CoreInteractionService(database).get(REQUEST.interaction_id)
        assert persisted is not None and persisted.response_pending_delivery
        original_response = persisted.response
        answered = await service.respond(REQUEST.interaction_id, "host-parameter")
        assert answered.state is InteractionLifecycle.ANSWERED
        assert original_response is not None
        assert transport.responses == [original_response, original_response]
        with pytest.raises(InteractionConflict, match="different immutable"):
            await service.respond(REQUEST.interaction_id, "different")

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()


def test_cancel_event_makes_pending_interaction_non_answerable(tmp_path: Path) -> None:
    database = _database(tmp_path / "core.sqlite3")
    try:
        receiver = CoreTransportReceiver(database)
        receiver.accept(_event_message())
        receiver.accept(_event_message("interaction.cancelled"))
        record = CoreInteractionService(database).get(REQUEST.interaction_id)
        assert record is not None
        assert record.state is InteractionLifecycle.CANCELLED
        assert not CoreInteractionService(database).list_pending()
    finally:
        database.dispose()
