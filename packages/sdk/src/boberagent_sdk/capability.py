"""Standard interface implemented by capability authors."""

from abc import ABC, abstractmethod
from typing import ClassVar

from boberagent_contracts import CapabilityId, CapabilityResult, OperationName
from pydantic import BaseModel

from .context import ExecutionContext


class Capability(ABC):
    """Transport-independent, multi-operation capability entry point."""

    capability_id: ClassVar[CapabilityId]

    @abstractmethod
    async def execute(
        self,
        operation: OperationName,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        """Execute one validated operation and return a Contract result."""
