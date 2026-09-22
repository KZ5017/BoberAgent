"""Core read model for one operator-facing interaction."""

from boberagent_contracts import (
    InteractionLifecycle,
    InteractionRequest,
    InteractionResponse,
)
from pydantic import AwareDatetime

from boberagent_core.models import CoreModel


class CoreInteraction(CoreModel):
    node_id: str
    request: InteractionRequest
    state: InteractionLifecycle
    response: InteractionResponse | None = None
    accepted_at: AwareDatetime | None = None
    cancelled_at: AwareDatetime | None = None
    cancellation_reason: str | None = None

    @property
    def response_pending_delivery(self) -> bool:
        return self.response is not None and self.state is InteractionLifecycle.REQUESTED
