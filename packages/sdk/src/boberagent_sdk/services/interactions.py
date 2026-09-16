"""Durable human/external Interaction boundary."""

from typing import Protocol

from boberagent_contracts import InteractionRequest, InteractionResponse


class InteractionService(Protocol):
    async def request(self, request: InteractionRequest) -> InteractionResponse: ...
