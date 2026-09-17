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
    InteractionSurfaceDeclaration,
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

execution_started = asyncio.Event()
allow_completion = asyncio.Event()


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
