"""Result, evidence, and semantic separation tests."""

from datetime import UTC, datetime

import pytest
from boberagent_contracts import (
    AccessMode,
    ArtifactDescriptor,
    ArtifactRef,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunRef,
    CapabilityRunStatus,
    Diagnostic,
    DiagnosticSeverity,
    Effect,
    EffectRef,
    EffectReversibility,
    Event,
    Finding,
    FindingRef,
    MissionRef,
    Observation,
    ObservationRef,
    ResourceDescriptor,
    ResourceRef,
    SessionDescriptor,
    SessionRef,
    StorageRef,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def test_empty_result_collections_are_valid() -> None:
    result = CapabilityResult(
        run_ref=CapabilityRunRef("run-1"),
        execution_status=CapabilityRunStatus.COMPLETED,
        outcome=CapabilityOutcome(category=CapabilityOutcomeCategory.SUCCESS),
    )

    assert result.observations == ()
    assert result.findings == ()
    assert result.artifacts == ()
    assert result.resources == ()
    assert result.sessions == ()
    assert result.effects == ()
    assert result.diagnostics == ()


@pytest.mark.parametrize(
    "category",
    [CapabilityOutcomeCategory.NEGATIVE, CapabilityOutcomeCategory.UNKNOWN],
)
def test_completed_run_can_have_non_success_assessment_outcome(
    category: CapabilityOutcomeCategory,
) -> None:
    result = CapabilityResult(
        run_ref=CapabilityRunRef("run-1"),
        execution_status=CapabilityRunStatus.COMPLETED,
        outcome=CapabilityOutcome(category=category),
    )

    assert result.execution_status is CapabilityRunStatus.COMPLETED
    assert result.outcome.category is category


def test_result_requires_terminal_execution_status() -> None:
    with pytest.raises(ValidationError, match="must be terminal"):
        CapabilityResult(
            run_ref=CapabilityRunRef("run-1"),
            execution_status=CapabilityRunStatus.RUNNING,
            outcome=CapabilityOutcome(category=CapabilityOutcomeCategory.PARTIAL),
        )


def test_observation_is_immutable_and_preserves_provenance() -> None:
    observation = Observation(
        observation_id=ObservationRef("observation-1"),
        type="network.service.state",
        subject_ref=MissionRef("mission-1"),
        value={"transport": "tcp", "port": 445, "state": "open"},
        run_ref=CapabilityRunRef("run-1"),
        observed_at=NOW,
        confidence=1.0,
        evidence_refs=(ArtifactRef("artifact-1"),),
    )

    assert observation.run_ref == CapabilityRunRef("run-1")
    assert observation.evidence_refs == (ArtifactRef("artifact-1"),)

    with pytest.raises(ValidationError, match="frozen"):
        observation.confidence = 0.5


def test_observation_rejects_non_json_runtime_objects() -> None:
    with pytest.raises(ValidationError):
        Observation.model_validate(
            {
                "observation_id": ObservationRef("observation-1"),
                "type": "example.value",
                "value": object(),
                "run_ref": CapabilityRunRef("run-1"),
                "observed_at": NOW,
            }
        )


def test_effect_round_trip_preserves_cleanup_metadata() -> None:
    effect = Effect(
        effect_id=EffectRef("effect-1"),
        type="target.account.created",
        action="create",
        run_ref=CapabilityRunRef("run-1"),
        occurred_at=NOW,
        intentional=True,
        confirmed=True,
        subject_ref=MissionRef("mission-1"),
        evidence_refs=(ArtifactRef("artifact-1"),),
        reversibility=EffectReversibility(
            reversible=True,
            cleanup_required=True,
            cleanup_status="pending",
            cleanup_capability_id="identity.account_remove",
            cleanup_inputs={"identity_ref": "identity-1"},
        ),
    )

    restored = Effect.model_validate_json(effect.model_dump_json())

    assert restored == effect
    assert restored.reversibility.cleanup_required is True


def test_capability_result_json_round_trip() -> None:
    observation = Observation(
        observation_id=ObservationRef("observation-1"),
        type="token.algorithm",
        value={"algorithm": "HS256"},
        run_ref=CapabilityRunRef("run-1"),
        observed_at=NOW,
    )
    result = CapabilityResult(
        run_ref=CapabilityRunRef("run-1"),
        execution_status=CapabilityRunStatus.COMPLETED,
        outcome=CapabilityOutcome(
            category=CapabilityOutcomeCategory.UNKNOWN,
            code="UNCLASSIFIED_RESULT",
        ),
        observations=(observation,),
    )

    restored = CapabilityResult.model_validate_json(result.model_dump_json())

    assert restored == result
    assert type(restored.run_ref) is CapabilityRunRef


def test_full_result_envelope_round_trips_all_descriptor_classes() -> None:
    artifact = ArtifactDescriptor(
        artifact_id=ArtifactRef("artifact-1"),
        artifact_type="process.stdout",
        storage_ref=StorageRef("storage://sha256/example"),
        created_by_run=CapabilityRunRef("run-1"),
        created_at=NOW,
        size_bytes=12,
        media_type="text/plain",
    )
    finding = Finding(
        finding_id=FindingRef("finding-1"),
        type="authentication.weakness",
        title="Candidate authentication weakness",
        description="Evidence supports a candidate authentication weakness.",
        run_ref=CapabilityRunRef("run-1"),
        created_at=NOW,
        observation_refs=(ObservationRef("observation-1"),),
    )
    resource = ResourceDescriptor(
        resource_id=ResourceRef("resource-1"),
        resource_type="listener",
        provider="test_provider",
        state="READY",
        owner_ref=MissionRef("mission-1"),
        created_by_run=CapabilityRunRef("run-1"),
        created_at=NOW,
        access_modes=(AccessMode.EXCLUSIVE,),
    )
    session = SessionDescriptor(
        session_id=SessionRef("session-1"),
        session_type="remote_shell",
        state="ACTIVE",
        provider="test_provider",
        owner_ref=MissionRef("mission-1"),
        created_by_run=CapabilityRunRef("run-1"),
        created_at=NOW,
        resource_refs=(ResourceRef("resource-1"),),
        supported_operations=("command_execute",),
        access_modes=(AccessMode.EXCLUSIVE,),
    )
    diagnostic = Diagnostic(
        code="OUTPUT_PARTIALLY_PARSED",
        severity=DiagnosticSeverity.WARNING,
        message="Some output could not be normalized.",
        occurred_at=NOW,
        run_ref=CapabilityRunRef("run-1"),
        artifact_refs=(ArtifactRef("artifact-1"),),
    )
    result = CapabilityResult(
        run_ref=CapabilityRunRef("run-1"),
        execution_status=CapabilityRunStatus.COMPLETED,
        outcome=CapabilityOutcome(category=CapabilityOutcomeCategory.PARTIAL),
        findings=(finding,),
        artifacts=(artifact,),
        resources=(resource,),
        sessions=(session,),
        diagnostics=(diagnostic,),
    )

    restored = CapabilityResult.model_validate_json(result.model_dump_json())

    assert restored == result


def test_normal_result_evidence_and_event_models_have_no_plaintext_secret_field() -> None:
    models = (CapabilityResult, Observation, Event, Diagnostic)

    for model in models:
        assert "secret" not in model.model_fields
        assert "plaintext_secret" not in model.model_fields
