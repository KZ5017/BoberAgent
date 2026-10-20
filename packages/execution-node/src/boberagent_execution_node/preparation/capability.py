"""Platform capability orchestration: SDK only, no provider or filesystem internals."""

from typing import ClassVar

from boberagent_contracts import (
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunStatus,
    RuntimePreparationInput,
)
from boberagent_sdk import Capability, ExecutionContext, InputError
from pydantic import BaseModel


class RuntimePreparationCapability(Capability):
    capability_id: ClassVar[str] = "runtime.prepare"

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        if operation != "prepare" or not isinstance(inputs, RuntimePreparationInput):
            raise InputError("Invalid preparation operation/input")
        if inputs.permit.run_ref != ctx.invocation.run_id:
            raise InputError("Preparation Run does not match context")
        receipt = await ctx.preparation.prepare_runtime(inputs)
        artifact = await ctx.artifacts.get(receipt.manifest_artifact_ref)
        return CapabilityResult(
            run_ref=ctx.invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(
                category=CapabilityOutcomeCategory.SUCCESS,
                code="RUNTIME_PREPARED",
                details={"preparation_receipt": receipt.model_dump(mode="json")},
            ),
            artifacts=(artifact,),
        )
