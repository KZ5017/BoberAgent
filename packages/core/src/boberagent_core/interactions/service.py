"""Core-owned interaction indexing and response delivery orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from boberagent_contracts import (
    Event,
    InteractionRef,
    InteractionRequest,
    InteractionResponse,
    JsonValue,
    validate_interaction_response,
)
from boberagent_transport import InteractionTransport
from pydantic import ValidationError

from boberagent_core.clock import utc_now
from boberagent_core.persistence import CoreDatabase

from .errors import InteractionConflict, InteractionNotFound
from .models import CoreInteraction


class CoreInteractionService:
    """Keep operator state durable and use only the neutral transport to answer."""

    def __init__(
        self,
        database: CoreDatabase,
        transport: InteractionTransport | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._database = database
        self._transport = transport
        self._clock = clock

    def observe_event(self, node_id: str, event: Event) -> CoreInteraction | None:
        if event.type == "interaction.requested":
            payload = event.payload.get("request")
            try:
                request = InteractionRequest.model_validate(payload)
            except ValidationError as error:
                raise InteractionConflict(
                    "interaction.requested contains an invalid request"
                ) from error
            if request.run_ref != event.source_ref or request.mission_ref != event.mission_ref:
                raise InteractionConflict("interaction.requested correlation is inconsistent")
            with self._database.unit_of_work() as work:
                return work.interactions.observe_request(node_id, request)
        if event.type == "interaction.cancelled":
            raw_ref = event.payload.get("interaction_ref")
            if not isinstance(raw_ref, str):
                raise InteractionConflict("interaction.cancelled lacks InteractionRef")
            reason = event.payload.get("reason")
            safe_reason = reason if isinstance(reason, str) and reason else "Interaction cancelled"
            with self._database.unit_of_work() as work:
                try:
                    return work.interactions.mark_cancelled(
                        InteractionRef(raw_ref),
                        cancelled_at=event.timestamp,
                        reason=safe_reason,
                    )
                except InteractionNotFound:
                    return None
        return None

    def get(self, interaction_ref: InteractionRef) -> CoreInteraction | None:
        with self._database.unit_of_work() as work:
            return work.interactions.get(interaction_ref)

    def list_pending(self) -> tuple[CoreInteraction, ...]:
        with self._database.unit_of_work() as work:
            return work.interactions.list_pending()

    def list_all(self) -> tuple[CoreInteraction, ...]:
        with self._database.unit_of_work() as work:
            return work.interactions.list_all()

    async def respond(self, interaction_ref: InteractionRef, value: JsonValue) -> CoreInteraction:
        transport = self._transport
        if transport is None:
            raise RuntimeError("Interaction response delivery requires a configured transport")
        with self._database.unit_of_work() as work:
            current = work.interactions.get(interaction_ref)
            if current is None:
                raise InteractionNotFound(f"unknown Interaction: {interaction_ref}")
            if current.response is not None:
                if current.response.value != value:
                    raise InteractionConflict(
                        "Interaction already has a different immutable response intent"
                    )
                response = current.response
            else:
                response = InteractionResponse(
                    interaction_ref=interaction_ref,
                    run_ref=current.request.run_ref,
                    responded_at=self._now(),
                    value=value,
                )
                try:
                    validate_interaction_response(current.request, response)
                except ValueError as error:
                    raise InteractionConflict(str(error)) from error
                work.interactions.record_response_intent(response)
            node_id = current.node_id
        acknowledgement = await transport.submit_interaction_response(node_id, response)
        with self._database.unit_of_work() as work:
            return work.interactions.mark_answered(
                interaction_ref,
                accepted_at=acknowledgement.accepted_at,
            )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Interaction clock must return timezone-aware datetime")
        return value
