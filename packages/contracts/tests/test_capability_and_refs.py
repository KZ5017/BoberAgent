"""Capability metadata, logical reference, invocation, and Run tests."""

from datetime import UTC, datetime

import pytest
from boberagent_contracts import (
    CONTRACT_VERSION,
    AssetRef,
    CapabilityDefinition,
    CapabilityInvocation,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    ExecutionCharacteristics,
    ExecutionDuration,
    ExecutionInteraction,
    InteractionSurfaceDeclaration,
    MissionRef,
    OperationDefinition,
    ResultObjectType,
    RetrySemantics,
    SchemaDeclaration,
    SideEffectCategory,
    SideEffectDeclaration,
    SideEffectLevel,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def operation_definition() -> OperationDefinition:
    return OperationDefinition(
        name="inspect",
        title="Inspect token",
        description="Inspect a token without target interaction.",
        input_schema=SchemaDeclaration(
            inline={
                "type": "object",
                "properties": {"artifact_ref": {"type": "string"}},
                "required": ["artifact_ref"],
            }
        ),
        result_types=(ResultObjectType.OBSERVATION,),
        retry_semantics=RetrySemantics.SAFE,
    )


def capability_definition() -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id="token.jwt_assessment",
        contract_version=CONTRACT_VERSION,
        implementation_version="0.1.0",
        title="JWT assessment",
        description="Analyze JWT material locally.",
        operations=(operation_definition(),),
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
                category=SideEffectCategory.TARGET_STATE,
                level=SideEffectLevel.NONE,
            ),
        ),
        dependencies=(),
    )


def test_reference_types_are_validated_and_runtime_distinct() -> None:
    mission_ref = MissionRef("mission-17")
    asset_ref = AssetRef("asset-17")

    assert str(mission_ref) == "mission-17"
    assert type(mission_ref) is MissionRef
    assert type(asset_ref) is AssetRef
    assert str(mission_ref) != str(asset_ref)

    with pytest.raises(ValueError):
        MissionRef("contains whitespace")

    with pytest.raises(ValueError):
        MissionRef("")


def test_wrong_typed_reference_is_rejected_before_serialization() -> None:
    data: dict[str, object] = {
        "run_id": CapabilityRunRef("run-1"),
        "capability_id": "token.jwt_assessment",
        "operation": "inspect",
        "mission_ref": AssetRef("asset-1"),
        "inputs": {},
    }

    with pytest.raises(ValidationError, match="expected MissionRef"):
        CapabilityInvocation.model_validate(data)


def test_capability_definition_validates_and_round_trips() -> None:
    definition = capability_definition()

    restored = CapabilityDefinition.model_validate_json(definition.model_dump_json())

    assert restored == definition
    assert restored.contract_version == CONTRACT_VERSION
    assert restored.operations[0].retry_semantics is RetrySemantics.SAFE


def test_capability_definition_rejects_duplicate_operations_and_wrong_major() -> None:
    definition = capability_definition()
    data = definition.model_dump(mode="python")
    data["operations"] = [operation_definition(), operation_definition()]

    with pytest.raises(ValidationError, match="operation names must be unique"):
        CapabilityDefinition.model_validate(data)

    data["operations"] = [operation_definition()]
    data["contract_version"] = "2.0"
    with pytest.raises(ValidationError, match="unsupported Capability Contract"):
        CapabilityDefinition.model_validate(data)


def test_schema_declaration_requires_exactly_one_source() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        SchemaDeclaration()

    with pytest.raises(ValidationError, match="exactly one"):
        SchemaDeclaration(inline={"type": "object"}, ref="schemas/input.json")


def test_target_independent_invocation_is_valid() -> None:
    invocation = CapabilityInvocation(
        run_id=CapabilityRunRef("run-1"),
        capability_id="secret.hash_recovery",
        operation="recover",
        mission_ref=MissionRef("mission-1"),
        inputs={"hash_artifact_ref": "artifact-72"},
    )

    assert "target_ref" not in invocation.model_fields_set
    assert invocation.inputs["hash_artifact_ref"] == "artifact-72"


@pytest.mark.parametrize(
    ("status", "expected_terminal"),
    [
        (CapabilityRunStatus.CREATED, False),
        (CapabilityRunStatus.RUNNING, False),
        (CapabilityRunStatus.WAITING_INPUT, False),
        (CapabilityRunStatus.COMPLETED, True),
        (CapabilityRunStatus.FAILED, True),
        (CapabilityRunStatus.CANCELLED, True),
        (CapabilityRunStatus.TIMED_OUT, True),
    ],
)
def test_run_lifecycle_terminal_semantics(
    status: CapabilityRunStatus,
    expected_terminal: bool,
) -> None:
    run = CapabilityRun(
        run_id=CapabilityRunRef("run-1"),
        capability_id="network.service_discovery",
        operation="discover",
        mission_ref=MissionRef("mission-1"),
        status=status,
        created_at=NOW,
    )

    assert run.is_terminal is expected_terminal
