"""PlanningAttempt-owned records in Core's existing durable interaction table."""

from copy import deepcopy
from datetime import datetime

from boberagent_contracts import InteractionLifecycle, InteractionRef, JsonObject
from pydantic import TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from boberagent_core.persistence.orm import InteractionRow
from boberagent_core.planning.interaction_models import (
    CorePlanningInteraction,
    PlanningInteractionRequest,
    PlanningInteractionResponse,
)
from boberagent_core.planning.models import PlanningAttemptRef

from .errors import InteractionConflict, InteractionNotFound, InteractionStateError

_json: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class PlanningInteractionRepository:
    """One immutable question/answer per exact planning context, in the caller's UoW."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, request: PlanningInteractionRequest) -> CorePlanningInteraction:
        request = PlanningInteractionRequest.model_validate_json(request.model_dump_json())
        payload = _json.validate_python(request.model_dump(mode="json"))
        self._session.execute(
            insert(InteractionRow)
            .values(
                interaction_id=str(request.interaction_ref),
                owner_kind="PLANNING_ATTEMPT",
                node_id=None,
                run_id=None,
                planning_attempt_id=str(request.planning_attempt_ref),
                purpose=request.purpose.value,
                proposal_revision=request.proposal_revision,
                policy_decision_id=(
                    None
                    if request.policy_decision_ref is None
                    else str(request.policy_decision_ref)
                ),
                mission_id=str(request.mission_ref),
                workflow_run_id=None,
                state=InteractionLifecycle.REQUESTED.value,
                request_json=payload,
                response_json=None,
                requested_at=request.requested_at,
                responded_at=None,
                accepted_at=None,
                cancelled_at=None,
                cancellation_reason=None,
            )
            .on_conflict_do_nothing()
        )
        found = self.get(request.interaction_ref)
        if found is not None:
            if found.request != request:
                raise InteractionConflict("InteractionRef identifies different planning content")
            return found
        existing = self.find_context(request)
        if existing is None:
            raise InteractionConflict("planning Interaction creation conflicted")
        if existing.request.model_dump(
            exclude={"interaction_ref", "requested_at"}
        ) != request.model_dump(exclude={"interaction_ref", "requested_at"}):
            raise InteractionConflict("planning Interaction context identifies different content")
        return existing

    def find_context(self, request: PlanningInteractionRequest) -> CorePlanningInteraction | None:
        query = select(InteractionRow).where(
            InteractionRow.owner_kind == "PLANNING_ATTEMPT",
            InteractionRow.planning_attempt_id == str(request.planning_attempt_ref),
            InteractionRow.purpose == request.purpose.value,
        )
        if request.policy_decision_ref is not None:
            query = query.where(
                InteractionRow.policy_decision_id == str(request.policy_decision_ref)
            )
        else:
            query = query.where(
                InteractionRow.policy_decision_id.is_(None),
                InteractionRow.proposal_revision == request.proposal_revision,
            )
        row = self._session.scalar(query)
        return None if row is None else _from_row(row)

    def get(self, ref: InteractionRef) -> CorePlanningInteraction | None:
        row = self._session.get(InteractionRow, str(ref), populate_existing=True)
        return None if row is None or row.owner_kind != "PLANNING_ATTEMPT" else _from_row(row)

    def list_pending(
        self, attempt_ref: PlanningAttemptRef | None = None
    ) -> tuple[CorePlanningInteraction, ...]:
        query = select(InteractionRow).where(
            InteractionRow.owner_kind == "PLANNING_ATTEMPT",
            InteractionRow.state == InteractionLifecycle.REQUESTED.value,
        )
        if attempt_ref is not None:
            query = query.where(InteractionRow.planning_attempt_id == str(attempt_ref))
        rows = self._session.scalars(query.order_by(InteractionRow.requested_at))
        return tuple(_from_row(row) for row in rows)

    def respond(self, response: PlanningInteractionResponse) -> CorePlanningInteraction:
        current = self.get(response.interaction_ref)
        if current is None:
            raise InteractionNotFound("unknown planning Interaction")
        request = current.request
        if (
            request.planning_attempt_ref != response.planning_attempt_ref
            or request.proposal_revision != response.proposal_revision
            or request.purpose is not response.purpose
        ):
            raise InteractionConflict("planning response owner, revision or purpose mismatch")
        if current.response is not None:
            if (
                current.response.value != response.value
                or current.response.operator_id != response.operator_id
            ):
                raise InteractionConflict("planning Interaction already has a different response")
            return current
        if current.state is not InteractionLifecycle.REQUESTED:
            raise InteractionStateError("planning Interaction is not answerable")
        payload = _json.validate_python(response.model_dump(mode="json"))
        result = self._session.connection().execute(
            update(InteractionRow)
            .where(
                InteractionRow.interaction_id == str(response.interaction_ref),
                InteractionRow.owner_kind == "PLANNING_ATTEMPT",
                InteractionRow.state == InteractionLifecycle.REQUESTED.value,
                InteractionRow.responded_at.is_(None),
            )
            .values(response_json=payload, responded_at=response.responded_at)
        )
        if result.rowcount != 1:
            raise InteractionConflict("planning Interaction response raced")
        accepted = self.get(response.interaction_ref)
        assert accepted is not None
        return accepted

    def mark_answered(
        self,
        ref: InteractionRef,
        *,
        accepted_at: datetime,
    ) -> CorePlanningInteraction:
        current = self.get(ref)
        if current is None:
            raise InteractionNotFound("unknown planning Interaction")
        if current.response is None:
            raise InteractionStateError("planning Interaction lacks a response")
        if current.state is InteractionLifecycle.ANSWERED:
            return current
        if current.state is not InteractionLifecycle.REQUESTED:
            raise InteractionStateError("planning Interaction is terminal")
        self._session.execute(
            update(InteractionRow)
            .where(InteractionRow.interaction_id == str(ref))
            .values(
                state=InteractionLifecycle.ANSWERED.value,
                accepted_at=accepted_at,
            )
        )
        updated = self.get(ref)
        assert updated is not None
        return updated


def _from_row(row: InteractionRow) -> CorePlanningInteraction:
    request = PlanningInteractionRequest.model_validate(deepcopy(row.request_json))
    if (
        row.planning_attempt_id != str(request.planning_attempt_ref)
        or row.mission_id != str(request.mission_ref)
        or row.purpose != request.purpose.value
        or row.proposal_revision != request.proposal_revision
        or row.policy_decision_id
        != (None if request.policy_decision_ref is None else str(request.policy_decision_ref))
        or row.node_id is not None
        or row.run_id is not None
    ):
        raise InteractionConflict("planning Interaction storage identity mismatch")
    return CorePlanningInteraction(
        request=request,
        state=InteractionLifecycle(row.state),
        response=None
        if row.response_json is None
        else PlanningInteractionResponse.model_validate(deepcopy(row.response_json)),
        accepted_at=row.accepted_at,
    )
