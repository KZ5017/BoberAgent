"""Synthetic capability providers used only by Execution Node tests."""

from __future__ import annotations

import hashlib
from typing import cast

from boberagent_contracts import (
    CONTRACT_VERSION,
    AssetRef,
    CapabilityDefinition,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunStatus,
    DependencyDeclaration,
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
    SecretRef,
    SideEffectCategory,
    SideEffectDeclaration,
    SideEffectLevel,
)
from boberagent_sdk import (
    Capability,
    ExecutionCancelled,
    ExecutionContext,
    ExecutionTimeout,
    ToolExecutionError,
)
from pydantic import BaseModel, ConfigDict, Field


class SyntheticInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_ref: AssetRef
    message: str = Field(min_length=1)
    timeout: float = Field(gt=0)


class SyntheticCapability(Capability):
    """Exercise the production Node services without becoming a real capability."""

    capability_id = "test.synthetic_runtime"

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        if operation not in {"run", "sleep"} or not isinstance(inputs, SyntheticInput):
            raise ValueError("unsupported synthetic operation or input")
        asset = await ctx.entities.asset(inputs.asset_ref)
        await ctx.scope.assert_asset_allowed(inputs.asset_ref)
        workspace = await ctx.workspace.create(purpose="synthetic-node-integration")
        if operation == "sleep":
            script = "import time; time.sleep(30)"
            args = ["-c", script]
        else:
            script = "import sys; print(sys.argv[1]); print('synthetic-stderr', file=sys.stderr)"
            args = ["-c", script, inputs.message]
        process = await ctx.processes.run_tool(
            tool="python",
            args=args,
            timeout=inputs.timeout,
        )
        if process.cancelled:
            raise ExecutionCancelled("synthetic process was cancelled")
        if process.timed_out:
            raise ExecutionTimeout("synthetic process timed out")
        if not process.succeeded:
            raise ToolExecutionError("synthetic process failed")

        output_path = workspace.path / "output.txt"
        output_path.write_bytes(process.stdout)
        artifact = await ctx.artifacts.create_from_file(
            artifact_type="test.synthetic_output",
            path=output_path,
            media_type="text/plain",
            metadata={
                "workspace_ref": str(workspace.workspace_ref),
                "address": asset.primary_address,
            },
        )
        await ctx.events.progress(message="synthetic execution complete", current=1, total=1)
        observation = Observation(
            observation_id=ObservationRef(f"observation-{ctx.invocation.run_id}"),
            type="test.synthetic",
            subject_ref=inputs.asset_ref,
            value={
                "message": inputs.message,
                "address": asset.primary_address,
                "stdout": process.stdout.decode(),
                "stderr": process.stderr.decode(),
            },
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


class InvalidResultCapability(Capability):
    """Deliberately violate the return contract to test runtime containment."""

    capability_id = "test.invalid_result"

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        del operation, ctx, inputs
        return cast(CapabilityResult, {"malformed": True})


class SecretConsumerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    secret_ref: SecretRef
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SecretConsumerCapability(Capability):
    """Resolve a granted Secret while returning only a safe verification result."""

    capability_id = "test.secret_consumer"

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        if operation != "verify" or not isinstance(inputs, SecretConsumerInput):
            raise ValueError("unsupported secret consumer operation or input")
        value = await ctx.secrets.resolve(
            inputs.secret_ref,
            purpose="test.secret_consumer:verify",
        )
        plaintext = value.reveal_bytes()
        verified = hashlib.sha256(plaintext).hexdigest() == inputs.expected_sha256
        ctx.logger.info(
            f"synthetic credential value={plaintext.decode('utf-8')}",
            secret_value=plaintext.decode("utf-8"),
            secret_ref=str(inputs.secret_ref),
        )
        return CapabilityResult(
            run_ref=ctx.invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(
                category=(
                    CapabilityOutcomeCategory.SUCCESS
                    if verified
                    else CapabilityOutcomeCategory.NEGATIVE
                )
            ),
        )


def capability_definition(
    *,
    capability_id: str = "test.synthetic_runtime",
    dependencies: tuple[DependencyDeclaration, ...] = (),
    operations: tuple[str, ...] = ("run", "sleep"),
) -> CapabilityDefinition:
    operation_definitions = tuple(
        OperationDefinition(
            name=operation,
            title=f"Synthetic {operation}",
            description="Exercise local Execution Node runtime services.",
            input_schema=SchemaDeclaration(
                inline={
                    "type": "object",
                    "required": ["asset_ref", "message", "timeout"],
                }
            ),
            result_types=(ResultObjectType.OBSERVATION, ResultObjectType.ARTIFACT),
            retry_semantics=RetrySemantics.SAFE,
        )
        for operation in operations
    )
    return CapabilityDefinition(
        capability_id=capability_id,
        contract_version=CONTRACT_VERSION,
        implementation_version="0.1.0",
        title="Synthetic Node capability",
        description="Test-only provider for the local runtime.",
        operations=operation_definitions,
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
        dependencies=dependencies,
    )


def capability_manifest(
    *,
    capability_id: str = "test.synthetic_runtime",
    implementation: str = ("boberagent_execution_node_test_capabilities:SyntheticCapability"),
    dependencies: tuple[DependencyDeclaration, ...] = (),
    operations: tuple[str, ...] = ("run", "sleep"),
    input_model: str = "boberagent_execution_node_test_capabilities:SyntheticInput",
) -> dict[str, object]:
    definition = capability_definition(
        capability_id=capability_id,
        dependencies=dependencies,
        operations=operations,
    )
    return {
        "definition": definition.model_dump(mode="json"),
        "implementation": implementation,
        "input_models": {operation: input_model for operation in operations},
    }
