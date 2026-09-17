"""Persistent local Event outbox and controlled SDK progress adapter."""

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from boberagent_contracts import (
    CapabilityRunRef,
    Event,
    EventRef,
    JsonObject,
    MissionRef,
)

from boberagent_execution_node.persistence import EventOutboxRecord, RuntimeStore


class EventOutbox:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def enqueue(self, event: Event) -> None:
        self._store.enqueue_event(event)

    def pending(self) -> tuple[EventOutboxRecord, ...]:
        return self._store.pending_events()

    def mark_delivered(self, sequence: int) -> None:
        self._store.mark_event_delivered(sequence)


class NodeEventService:
    """SDK EventService exposing only capability-owned progress events."""

    def __init__(
        self,
        *,
        outbox: EventOutbox,
        mission_ref: MissionRef,
        run_ref: CapabilityRunRef,
        clock: Callable[[], datetime],
    ) -> None:
        self._outbox = outbox
        self._mission_ref = mission_ref
        self._run_ref = run_ref
        self._clock = clock

    async def progress(
        self,
        *,
        message: str,
        current: int | None = None,
        total: int | None = None,
        metadata: JsonObject | None = None,
    ) -> Event:
        if not message:
            raise ValueError("progress message must not be empty")
        if current is not None and current < 0:
            raise ValueError("progress current must be non-negative")
        if total is not None and total < 0:
            raise ValueError("progress total must be non-negative")
        if current is not None and total is not None and current > total:
            raise ValueError("progress current must not exceed total")
        return self._emit(
            "capability.progress",
            {
                "message": message,
                "current": current,
                "total": total,
                "metadata": {} if metadata is None else metadata,
            },
        )

    def runtime_event(self, event_type: str, payload: JsonObject) -> Event:
        """Node-runtime-only lifecycle emission, not exposed through ExecutionContext."""

        return self._emit(event_type, payload)

    def _emit(self, event_type: str, payload: JsonObject) -> Event:
        event = Event(
            event_id=EventRef(f"event-{uuid4()}"),
            type=event_type,
            timestamp=self._clock(),
            mission_ref=self._mission_ref,
            source_ref=self._run_ref,
            payload=payload,
        )
        self._outbox.enqueue(event)
        return event
