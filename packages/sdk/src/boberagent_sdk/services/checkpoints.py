"""Serializable capability continuation checkpoint interface."""

from typing import Protocol

from boberagent_contracts import Checkpoint, CheckpointRef


class CheckpointService(Protocol):
    async def save(self, checkpoint: Checkpoint) -> None: ...

    async def load(self, checkpoint_ref: CheckpointRef) -> Checkpoint | None: ...
