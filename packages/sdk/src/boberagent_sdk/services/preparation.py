"""Typed E1 preparation port; no production provider is registered yet."""

from typing import Protocol

from boberagent_contracts import RuntimePreparationInput, RuntimePreparationReceipt


class RuntimePreparationService(Protocol):
    """Future provider-owned operation; never an arbitrary process/command interface."""

    async def prepare_runtime(
        self, request: RuntimePreparationInput
    ) -> RuntimePreparationReceipt: ...
