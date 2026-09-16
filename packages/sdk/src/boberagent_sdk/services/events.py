"""Controlled capability-owned event emission."""

from typing import Protocol

from boberagent_contracts import Event, JsonObject


class EventService(Protocol):
    """Expose safe event operations rather than arbitrary event impersonation."""

    async def progress(
        self,
        *,
        message: str,
        current: int | None = None,
        total: int | None = None,
        metadata: JsonObject | None = None,
    ) -> Event: ...
