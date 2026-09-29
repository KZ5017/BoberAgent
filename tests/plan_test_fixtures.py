"""Non-executing shared D1 intent fixture; no source/process/network services."""

from datetime import UTC, datetime

from boberagent_contracts import (
    ArtifactRef,
    AssetRef,
    ExecutionPlanRef,
    ExecutionPlanV2,
    MissionRef,
    PoCAcquisitionRef,
)
from boberagent_contracts.plan_requirements import (
    EffectScope,
    ExecutionLimits,
    ExecutionLocation,
    ExpectedEvidence,
    FilesystemConstraints,
    NetworkConstraints,
    NetworkDestinationClass,
    NetworkRule,
    PlanSource,
    RuntimeRequirement,
)
from boberagent_contracts.plan_values import (
    BindingProvenance,
    DeliveryChannel,
    EntrypointIntent,
    FlagToken,
    InvocationLayout,
    LiteralValue,
    MissionTargetValue,
    NetworkTarget,
    OptionValueToken,
    ParameterBinding,
    PositionalToken,
    ResolutionState,
    TargetRole,
    ValueType,
)

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


def plan_fixture() -> ExecutionPlanV2:
    return ExecutionPlanV2(
        execution_plan_id=ExecutionPlanRef("plan-d1"),
        mission_ref=MissionRef("mission-d1"),
        source=PlanSource(
            acquisition_ref=PoCAcquisitionRef("acquisition-d1"),
            raw_artifact_ref=ArtifactRef("artifact-raw"),
            raw_sha256="a" * 64,
            raw_size_bytes=200,
            manifest_artifact_ref=ArtifactRef("artifact-manifest"),
            manifest_sha256="b" * 64,
            resolved_commit="c" * 40,
        ),
        target=NetworkTarget(
            role=TargetRole.IP, asset_ref=AssetRef("asset-d1"), address="127.0.0.1"
        ),
        entrypoint=EntrypointIntent(
            relative_path="src/check.py",
            entry_sha256="d" * 64,
            language="python",
            invocation_form="SCRIPT",
            evidence_ids=("entry-evidence-1",),
        ),
        runtime=RuntimeRequirement(
            kind="python",
            version_constraint=">=3.12",
            platform="LINUX",
            platform_variant="kali",
            user_space=True,
            noninteractive=True,
            location=ExecutionLocation.ATTACKER_NODE,
        ),
        invocation=InvocationLayout(
            review_id="review-1",
            evidence_ids=("entry-evidence-1",),
            arguments=(
                PositionalToken(binding_id="target"),
                OptionValueToken(name="--timeout", binding_id="timeout"),
                FlagToken(name="--quiet"),
            ),
        ),
        bindings=(
            ParameterBinding(
                binding_id="target",
                parameter_id="host",
                value_type=ValueType.TARGET,
                channel=DeliveryChannel.ARGUMENT,
                required=True,
                resolution=ResolutionState.RESOLVED,
                value=MissionTargetValue(target_role=TargetRole.IP),
                provenance=BindingProvenance(origin="MISSION"),
            ),
            ParameterBinding(
                binding_id="timeout",
                parameter_id="timeout",
                value_type=ValueType.INTEGER,
                channel=DeliveryChannel.ARGUMENT,
                required=False,
                resolution=ResolutionState.RESOLVED,
                value=LiteralValue(value=30),
                provenance=BindingProvenance(origin="PLANNING"),
            ),
        ),
        filesystem=FilesystemConstraints(scope=EffectScope.BOUNDED, cleanup="RETAIN_EVIDENCE"),
        network=NetworkConstraints(
            rules=(
                NetworkRule(
                    destination=NetworkDestinationClass.SELECTED_TARGET,
                    transport="tcp",
                    ports=(80,),
                ),
            )
        ),
        limits=ExecutionLimits(
            wall_time_seconds=30,
            process_count=1,
            memory_bytes=1024**3,
            output_bytes=1024**2,
            disk_write_bytes=0,
        ),
        expected_evidence=(
            ExpectedEvidence(evidence_id="stdout", kind="STDOUT", semantic_type="poc.output"),
        ),
        created_at=NOW,
    )
