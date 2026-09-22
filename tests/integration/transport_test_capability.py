"""Synthetic Capability used only by Milestone 5 transport integration tests."""

from __future__ import annotations

import asyncio

from boberagent_contracts import (
    CONTRACT_VERSION,
    AssetRef,
    CapabilityDefinition,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunStatus,
    ExecutionCharacteristics,
    ExecutionDuration,
    ExecutionInteraction,
    InteractionOption,
    InteractionRef,
    InteractionRequest,
    InteractionSurfaceDeclaration,
    InteractionType,
    Observation,
    ObservationRef,
    OperationDefinition,
    ResultObjectType,
    RetrySemantics,
    SchemaDeclaration,
    SideEffectCategory,
    SideEffectDeclaration,
    SideEffectLevel,
)
from boberagent_sdk import Capability, ExecutionContext
from pydantic import BaseModel, ConfigDict


class ResettableEvent:
    """Test event that can be safely reused across separate asyncio.run() loops."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def set(self) -> None:
        self._event.set()

    def clear(self) -> None:
        self._event = asyncio.Event()

    async def wait(self) -> bool:
        return await self._event.wait()


execution_started = ResettableEvent()
allow_completion = ResettableEvent()


def reset_control() -> None:
    execution_started.clear()
    allow_completion.clear()
    TransportSyntheticCapability.execution_count = 0


class TransportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_ref: AssetRef
    message: str
    wait_for_release: bool = False


class TransportSyntheticCapability(Capability):
    capability_id = "test.transport_synthetic"
    execution_count = 0

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        if operation != "execute" or not isinstance(inputs, TransportInput):
            raise ValueError("unsupported test operation/input")
        type(self).execution_count += 1
        asset = await ctx.entities.asset(inputs.asset_ref)
        await ctx.scope.assert_asset_allowed(inputs.asset_ref)
        execution_started.set()
        if inputs.wait_for_release:
            await allow_completion.wait()
        workspace = await ctx.workspace.create(purpose="transport-integration")
        output = workspace.path / "transport.txt"
        output.write_text(inputs.message, encoding="utf-8")
        artifact = await ctx.artifacts.create_from_file(
            artifact_type="test.transport_output",
            path=output,
            media_type="text/plain",
            metadata={"address": asset.primary_address},
        )
        await ctx.events.progress(message="transport synthetic complete", current=1, total=1)
        observation = Observation(
            observation_id=ObservationRef(f"observation-{ctx.invocation.run_id}"),
            type="test.transport",
            subject_ref=inputs.asset_ref,
            value={"message": inputs.message, "address": asset.primary_address},
            run_ref=ctx.invocation.run_id,
            observed_at=ctx.clock.now(),
            confidence=1.0,
            evidence_refs=(artifact.artifact_id,),
        )
        return CapabilityResult(
            run_ref=ctx.invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(category=CapabilityOutcomeCategory.SUCCESS),
            observations=(observation,),
            artifacts=(artifact,),
        )


class InteractiveInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InteractiveSyntheticCapability(Capability):
    """Test-only capability proving the real SDK interaction boundary."""

    capability_id = "test.human_interaction"
    execution_count = 0

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        if operation != "run" or not isinstance(inputs, InteractiveInput):
            raise ValueError("unsupported interactive test operation/input")
        type(self).execution_count += 1
        requests = (
            InteractionRequest(
                interaction_id=InteractionRef(f"interaction-{ctx.invocation.run_id}-confirm"),
                run_ref=ctx.invocation.run_id,
                mission_ref=ctx.invocation.mission_ref,
                workflow_run_ref=ctx.invocation.workflow_run_ref,
                interaction_type=InteractionType.CONFIRMATION,
                title="Continue synthetic test?",
                description="Confirm a harmless interaction test.",
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
                title="Harmless identifier",
                description="Provide a non-secret test identifier.",
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
                description="Choose a deterministic harmless completion mode.",
                input_schema={"type": "string", "enum": ["normal", "stop"]},
                resume_semantics="same_run",
                requested_at=ctx.clock.now(),
                options=(
                    InteractionOption(option_id="normal", label="Complete normally"),
                    InteractionOption(option_id="stop", label="Stop"),
                ),
            ),
        )
        responses = [await ctx.interactions.request(request) for request in requests]
        return CapabilityResult(
            run_ref=ctx.invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(
                category=(
                    CapabilityOutcomeCategory.SUCCESS
                    if responses[0].value is True and responses[2].value == "normal"
                    else CapabilityOutcomeCategory.NEGATIVE
                ),
                summary="Synthetic operator inputs were received.",
            ),
        )


def capability_manifest() -> dict[str, object]:
    definition = CapabilityDefinition(
        capability_id="test.transport_synthetic",
        contract_version=CONTRACT_VERSION,
        implementation_version="0.1.0",
        title="Transport synthetic",
        description="Test-only capability exercising transport and Node SDK services.",
        operations=(
            OperationDefinition(
                name="execute",
                title="Execute transport fixture",
                description="Create one Artifact and Observation for transport testing.",
                input_schema=SchemaDeclaration(
                    inline={
                        "type": "object",
                        "required": ["asset_ref", "message"],
                    }
                ),
                result_types=(ResultObjectType.OBSERVATION, ResultObjectType.ARTIFACT),
                retry_semantics=RetrySemantics.SAFE,
            ),
        ),
        execution=ExecutionCharacteristics(
            duration=ExecutionDuration.ONE_SHOT,
            interaction=ExecutionInteraction.STATELESS,
            supports_cancellation=True,
        ),
        interaction_surfaces=InteractionSurfaceDeclaration(
            local_compute=True,
            target_network=False,
            internet_access=False,
            active_session=False,
            managed_resource=False,
        ),
        side_effects=(
            SideEffectDeclaration(
                category=SideEffectCategory.LOCAL_FILESYSTEM,
                level=SideEffectLevel.WRITE,
            ),
        ),
        dependencies=(),
    )
    module = "transport_test_capability"
    return {
        "definition": definition.model_dump(mode="json"),
        "implementation": f"{module}:TransportSyntheticCapability",
        "input_models": {"execute": f"{module}:TransportInput"},
    }


def interaction_capability_manifest() -> dict[str, object]:
    definition = CapabilityDefinition(
        capability_id="test.human_interaction",
        contract_version=CONTRACT_VERSION,
        implementation_version="0.1.0",
        title="Synthetic human interaction",
        description="Test-only capability exercising durable structured operator input.",
        operations=(
            OperationDefinition(
                name="run",
                title="Request structured input",
                description="Request confirmation, text, and one choice in sequence.",
                input_schema=SchemaDeclaration(inline={"type": "object"}),
                result_types=(),
                retry_semantics=RetrySemantics.UNSAFE,
            ),
        ),
        execution=ExecutionCharacteristics(
            duration=ExecutionDuration.LONG_RUNNING,
            interaction=ExecutionInteraction.STATEFUL,
            supports_cancellation=True,
        ),
        interaction_surfaces=InteractionSurfaceDeclaration(
            local_compute=True,
            target_network=False,
            internet_access=False,
            active_session=False,
            managed_resource=False,
        ),
        side_effects=(
            SideEffectDeclaration(
                category=SideEffectCategory.LOCAL_FILESYSTEM,
                level=SideEffectLevel.NONE,
            ),
        ),
        dependencies=(),
    )
    module = "transport_test_capability"
    return {
        "definition": definition.model_dump(mode="json"),
        "implementation": f"{module}:InteractiveSyntheticCapability",
        "input_models": {"run": f"{module}:InteractiveInput"},
    }
