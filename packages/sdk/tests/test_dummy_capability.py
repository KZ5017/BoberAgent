"""SDK-only reference flow proving capability author ergonomics."""

import asyncio

from boberagent_contracts import (
    AssetRef,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunStatus,
    Observation,
    ObservationRef,
)
from boberagent_sdk import AssetSnapshot, Capability, ExecutionContext, ProcessResult
from boberagent_sdk.testing import FakeExecutionContext
from pydantic import BaseModel, ConfigDict, Field


class DiscoveryInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_ref: AssetRef
    timeout: float = Field(gt=0)


class DummyDiscoveryCapability(Capability):
    """Test fixture only; this is not the production service-discovery capability."""

    capability_id = "test.service_discovery"

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        if operation != "discover" or not isinstance(inputs, DiscoveryInput):
            raise ValueError("unsupported test operation/input")
        asset = await ctx.entities.asset(inputs.asset_ref)
        await ctx.scope.assert_asset_allowed(inputs.asset_ref)
        workspace = await ctx.workspace.create(purpose="dummy-service-discovery")
        output_path = workspace.path / "scan.xml"
        process = await ctx.processes.run_tool(
            tool="fixture-scanner",
            args=["--xml", str(output_path), asset.primary_address],
            timeout=inputs.timeout,
        )
        output_path.write_bytes(process.stdout)
        artifact = await ctx.artifacts.create_from_file(
            artifact_type="network.scan.xml",
            path=output_path,
            media_type="application/xml",
        )
        observation = Observation(
            observation_id=ObservationRef("observation-dummy-service"),
            type="network.service",
            subject_ref=inputs.asset_ref,
            value={
                "transport": "tcp",
                "port": 443,
                "state": "open",
                "service": "https",
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


def test_dummy_capability_complete_fake_flow() -> None:
    context = FakeExecutionContext()
    asset = AssetSnapshot(
        ref=AssetRef("asset-dummy"),
        primary_address="203.0.113.9",
    )
    context.entities.add(asset)
    context.scope.allow_asset(asset.ref)
    probe = asyncio.run(context.workspace.create(purpose="discover-test-root"))
    workspace_root = probe.path.parent
    asyncio.run(context.workspace.cleanup(probe.workspace_ref))
    expected_args = [
        "--xml",
        str(workspace_root / "workspace-0002" / "scan.xml"),
        asset.primary_address,
    ]
    context.processes.expect_tool(
        tool="fixture-scanner",
        args=expected_args,
        timeout=60,
        result=ProcessResult(exit_code=0, stdout=b"<scan />"),
    )
    try:
        result = asyncio.run(
            DummyDiscoveryCapability().execute(
                "discover",
                context,
                DiscoveryInput(asset_ref=asset.ref, timeout=60),
            )
        )
        context.processes.assert_expectations_met()
        assert result.execution_status is CapabilityRunStatus.COMPLETED
        assert result.observations[0].run_ref == context.invocation.run_id
        assert result.observations[0].evidence_refs == (result.artifacts[0].artifact_id,)
        assert result.model_validate_json(result.model_dump_json()) == result
    finally:
        context.close()
