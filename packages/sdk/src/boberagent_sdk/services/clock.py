"""Platform-consistent clock interface."""

from datetime import UTC, datetime
from typing import Protocol


class ClockService(Protocol):
    def now(self) -> datetime:
        """Return an aware platform timestamp."""


class UtcClock:
    """Infrastructure-free default clock for simple runtime adapters."""

    def now(self) -> datetime:
        return datetime.now(UTC)
