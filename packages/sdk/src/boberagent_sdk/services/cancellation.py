"""Cooperative cancellation interface."""

from typing import Protocol


class CancellationService(Protocol):
    @property
    def requested(self) -> bool: ...

    async def checkpoint(self) -> None:
        """Raise ExecutionCancelled when cancellation has been requested."""
