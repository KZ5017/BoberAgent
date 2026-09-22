"""Harmless manual-only HITL fixture; not a production capability package."""

from boberagent_contracts import (
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunStatus,
    InteractionOption,
    InteractionRef,
    InteractionRequest,
    InteractionType,
)
from boberagent_sdk import Capability, ExecutionContext
from pydantic import BaseModel, ConfigDict


class ManualInteractionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ManualInteractionCapability(Capability):
    capability_id = "test.manual_human_interaction"

    async def execute(
        self, operation: str, ctx: ExecutionContext, inputs: BaseModel
    ) -> CapabilityResult:
        if operation != "run" or not isinstance(inputs, ManualInteractionInput):
            raise ValueError("unsupported manual interaction operation/input")
        requests = (
            InteractionRequest(
                interaction_id=InteractionRef(f"interaction-{ctx.invocation.run_id}-confirm"),
                run_ref=ctx.invocation.run_id,
                mission_ref=ctx.invocation.mission_ref,
                workflow_run_ref=ctx.invocation.workflow_run_ref,
                interaction_type=InteractionType.CONFIRMATION,
                title="Continue manual HITL smoke test?",
                description="This is a harmless transport and persistence check.",
                input_schema={"type": "boolean"},
                resume_semantics="same_run",
                requested_at=ctx.clock.now(),
            ),
            InteractionRequest(
                interaction_id=InteractionRef(f"interaction-{ctx.invocation.run_id}-text"),
                run_ref=ctx.invocation.run_id,
                mission_ref=ctx.invocation.mission_ref,
                workflow_run_ref=ctx.invocation.workflow_run_ref,
                interaction_type=InteractionType.TEXT,
                title="Harmless label",
                description="Enter a non-secret label such as lab-check.",
                input_schema={"type": "string", "minLength": 1, "maxLength": 64},
                resume_semantics="same_run",
                requested_at=ctx.clock.now(),
            ),
            InteractionRequest(
                interaction_id=InteractionRef(f"interaction-{ctx.invocation.run_id}-choice"),
                run_ref=ctx.invocation.run_id,
                mission_ref=ctx.invocation.mission_ref,
                workflow_run_ref=ctx.invocation.workflow_run_ref,
                interaction_type=InteractionType.SINGLE_CHOICE,
                title="Completion mode",
                description="Choose normal completion or a negative test outcome.",
                input_schema={"type": "string", "enum": ["normal", "stop"]},
                resume_semantics="same_run",
                requested_at=ctx.clock.now(),
                options=(
                    InteractionOption(option_id="normal", label="Complete normally"),
                    InteractionOption(option_id="stop", label="Return negative"),
                ),
            ),
        )
        responses = [await ctx.interactions.request(request) for request in requests]
        successful = responses[0].value is True and responses[2].value == "normal"
        return CapabilityResult(
            run_ref=ctx.invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(
                category=(
                    CapabilityOutcomeCategory.SUCCESS
                    if successful
                    else CapabilityOutcomeCategory.NEGATIVE
                ),
                summary="Manual structured interaction inputs were received.",
            ),
        )
