"""Closed preparation port; implementations cannot grant execution authority."""

from typing import Protocol

from boberagent_contracts import RuntimePreparationInput, RuntimePreparationReceipt

from ..exceptions import DependencyError


class RuntimePreparationService(Protocol):
    """Provider-owned operation; never an arbitrary process/command interface."""

    async def prepare_runtime(
        self, request: RuntimePreparationInput
    ) -> RuntimePreparationReceipt: ...


class UnavailableRuntimePreparationService:
    async def prepare_runtime(self, request: RuntimePreparationInput) -> RuntimePreparationReceipt:
        del request
        raise DependencyError("No admitted preparation service is bound to this Run")
