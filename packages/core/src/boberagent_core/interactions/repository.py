"""Private SQLAlchemy mapping for durable Core interaction state."""

from copy import deepcopy
from datetime import datetime

from boberagent_contracts import (
    InteractionLifecycle,
    InteractionRef,
    InteractionRequest,
    InteractionResponse,
    JsonObject,
)
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from boberagent_core.persistence.orm import InteractionRow

from .errors import InteractionConflict, InteractionNotFound, InteractionStateError
from .models import CoreInteraction

_json_object_adapter: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class InteractionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def observe_request(self, node_id: str, request: InteractionRequest) -> CoreInteraction:
        request_json = _json_object_adapter.validate_python(request.model_dump(mode="json"))
        row = self._session.get(InteractionRow, str(request.interaction_id))
        if row is not None:
            if row.node_id != node_id or row.request_json != request_json:
                raise InteractionConflict(
                    f"InteractionRef identifies conflicting request content: {request.interaction_id}"
                )
            return _from_row(row)
        row = InteractionRow(
            interaction_id=str(request.interaction_id),
            node_id=node_id,
            run_id=str(request.run_ref),
            mission_id=str(request.mission_ref),
            workflow_run_id=(
                None if request.workflow_run_ref is None else str(request.workflow_run_ref)
            ),
            state=InteractionLifecycle.REQUESTED.value,
            request_json=request_json,
            response_json=None,
            requested_at=request.requested_at,
            responded_at=None,
            accepted_at=None,
            cancelled_at=None,
            cancellation_reason=None,
        )
        self._session.add(row)
        self._session.flush()
        return _from_row(row)

    def get(self, interaction_ref: InteractionRef) -> CoreInteraction | None:
        row = self._session.get(InteractionRow, str(interaction_ref))
        return None if row is None else _from_row(row)

    def list_pending(self) -> tuple[CoreInteraction, ...]:
        rows = self._session.scalars(
            select(InteractionRow)
            .where(InteractionRow.state == InteractionLifecycle.REQUESTED.value)
            .order_by(InteractionRow.requested_at, InteractionRow.interaction_id)
        )
        return tuple(_from_row(row) for row in rows if row.response_json is None)

    def list_all(self) -> tuple[CoreInteraction, ...]:
        rows = self._session.scalars(
            select(InteractionRow).order_by(
                InteractionRow.requested_at, InteractionRow.interaction_id
            )
        )
        return tuple(_from_row(row) for row in rows)

    def record_response_intent(self, response: InteractionResponse) -> CoreInteraction:
        row = self._required(response.interaction_ref)
        response_json = _json_object_adapter.validate_python(response.model_dump(mode="json"))
        if row.response_json is not None:
            if row.response_json != response_json:
                raise InteractionConflict("Interaction already has a different immutable response")
            return _from_row(row)
        if InteractionLifecycle(row.state) is not InteractionLifecycle.REQUESTED:
            raise InteractionStateError(f"Interaction is not answerable: {row.state}")
        row.response_json = response_json
        row.responded_at = response.responded_at
        self._session.flush()
        return _from_row(row)

    def mark_answered(
        self, interaction_ref: InteractionRef, *, accepted_at: datetime
    ) -> CoreInteraction:
        row = self._required(interaction_ref)
        if row.response_json is None:
            raise InteractionStateError("Interaction has no durable response intent")
        if InteractionLifecycle(row.state) is InteractionLifecycle.CANCELLED:
            raise InteractionStateError("Cancelled Interaction cannot become answered")
        row.state = InteractionLifecycle.ANSWERED.value
        row.accepted_at = row.accepted_at or accepted_at
        self._session.flush()
        return _from_row(row)

    def mark_cancelled(
        self,
        interaction_ref: InteractionRef,
        *,
        cancelled_at: datetime,
        reason: str,
    ) -> CoreInteraction:
        row = self._required(interaction_ref)
        state = InteractionLifecycle(row.state)
        if state is InteractionLifecycle.ANSWERED:
            return _from_row(row)
        row.state = InteractionLifecycle.CANCELLED.value
        row.cancelled_at = row.cancelled_at or cancelled_at
        row.cancellation_reason = row.cancellation_reason or reason
        self._session.flush()
        return _from_row(row)

    def _required(self, interaction_ref: InteractionRef) -> InteractionRow:
        row = self._session.get(InteractionRow, str(interaction_ref))
        if row is None:
            raise InteractionNotFound(f"unknown Interaction: {interaction_ref}")
        return row


def _from_row(row: InteractionRow) -> CoreInteraction:
    return CoreInteraction(
        node_id=row.node_id,
        request=InteractionRequest.model_validate(deepcopy(row.request_json)),
        state=InteractionLifecycle(row.state),
        response=(
            None
            if row.response_json is None
            else InteractionResponse.model_validate(deepcopy(row.response_json))
        ),
        accepted_at=row.accepted_at,
        cancelled_at=row.cancelled_at,
        cancellation_reason=row.cancellation_reason,
    )
