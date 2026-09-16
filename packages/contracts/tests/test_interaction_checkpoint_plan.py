"""Durable interaction, Checkpoint, and ExecutionPlan model tests."""

from datetime import UTC, datetime

import pytest
from boberagent_contracts import (
    ArtifactRef,
    CapabilityRunRef,
    Checkpoint,
    CheckpointRef,
    DependencyDeclaration,
    DependencyType,
    ExecutionPlan,
    ExecutionPlanRef,
    ExecutionPlanStatus,
    InteractionRef,
    InteractionRequest,
    InteractionResponse,
    InteractionType,
    IsolationRequirement,
    ResourceRef,
    SecretRef,
    SessionRef,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def test_interaction_request_validates_structured_input_schema() -> None:
    request = InteractionRequest(
        interaction_id=InteractionRef("interaction-1"),
        run_ref=CapabilityRunRef("run-1"),
        interaction_type=InteractionType.CHOICE,
        title="Choose a payload family",
        description="Known variants did not establish a session.",
        input_schema={"type": "string", "enum": ["python", "php", "stop"]},
        resume_semantics="same_run",
        requested_at=NOW,
    )

    assert request.input_schema["type"] == "string"

    with pytest.raises(ValidationError, match="top-level type"):
        InteractionRequest(
            interaction_id=InteractionRef("interaction-2"),
            run_ref=CapabilityRunRef("run-1"),
            interaction_type=InteractionType.TEXT_INPUT,
            title="Provide input",
            description="Input is required to continue.",
            input_schema={"description": "missing type"},
            resume_semantics="same_run",
            requested_at=NOW,
        )


def test_secret_interaction_response_uses_secret_reference() -> None:
    response = InteractionResponse(
        interaction_ref=InteractionRef("interaction-1"),
        run_ref=CapabilityRunRef("run-1"),
        responded_at=NOW,
        secret_ref=SecretRef("secret-1"),
    )

    assert response.secret_ref == SecretRef("secret-1")
    assert response.value is None

    with pytest.raises(ValidationError, match="exactly one"):
        InteractionResponse(
            interaction_ref=InteractionRef("interaction-1"),
            run_ref=CapabilityRunRef("run-1"),
            responded_at=NOW,
            value="plaintext",
            secret_ref=SecretRef("secret-1"),
        )


def test_checkpoint_is_serializable_logical_state() -> None:
    checkpoint = Checkpoint(
        checkpoint_id=CheckpointRef("checkpoint-1"),
        run_ref=CapabilityRunRef("run-1"),
        phase="wait_for_input",
        state={"attempted_variants": ["bash", "python"], "next_step": "retry_custom"},
        created_at=NOW,
        artifact_refs=(ArtifactRef("artifact-1"),),
        resource_refs=(ResourceRef("resource-1"),),
        session_refs=(SessionRef("session-1"),),
        pending_interaction_ref=InteractionRef("interaction-1"),
    )

    restored = Checkpoint.model_validate_json(checkpoint.model_dump_json())

    assert restored == checkpoint


def test_execution_plan_round_trip_represents_intent_only() -> None:
    plan = ExecutionPlan(
        execution_plan_id=ExecutionPlanRef("plan-1"),
        source_artifact_ref=ArtifactRef("artifact-poc-1"),
        status=ExecutionPlanStatus.VALIDATED,
        runtime_type="python",
        runtime_version="3.12",
        isolation=IsolationRequirement(
            profile="python_venv",
            requirements={"network": "target_only"},
        ),
        dependencies=(
            DependencyDeclaration(
                dependency_type=DependencyType.RUNTIME,
                identifier="python",
                version_spec=">=3.12",
            ),
        ),
        entrypoint="poc.py",
        argument_bindings={"target": {"asset_ref": "asset-1"}},
        resource_refs=(ResourceRef("listener-1"),),
        expected_outcomes=("session_created", "target_not_vulnerable"),
        uncertainties=("PoC success marker is undocumented.",),
        created_at=NOW,
        created_by_run=CapabilityRunRef("run-inspection-1"),
    )

    restored = ExecutionPlan.model_validate_json(plan.model_dump_json())

    assert restored == plan
    assert restored.status is ExecutionPlanStatus.VALIDATED
