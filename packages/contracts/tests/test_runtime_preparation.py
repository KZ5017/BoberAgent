"""M20-E1 typed intent and evidence, without admission or preparation side effects."""

from datetime import UTC, datetime, timedelta

import pytest
from boberagent_contracts import (
    CapabilityRunRef,
    ExecutionPlanRef,
    MissionRef,
    PlanDecisionRef,
    PreparationPermitRef,
    ResourceRef,
    RuntimePreparationManifestRef,
    RuntimePreparationRef,
)
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_contracts.runtime_preparation import (
    ConfinementFeature,
    PreparationAction,
    PreparationBudgets,
    PreparationPermit,
    PreparationReasonCategory,
    PreparationReasonCode,
    RuntimePreparationInput,
    RuntimePreparationManifest,
    RuntimePreparationReceipt,
    RuntimePreparationSpec,
    preparation_manifest_digest,
    preparation_permit_digest,
    preparation_profile_digest,
    preparation_spec_fingerprint,
)
from plan_test_fixtures import NOW, plan_fixture
from preparation_test_fixtures import (
    manifest_fixture,
    permit_fixture,
    receipt_fixture,
    spec_fixture,
)
from pydantic import ValidationError


def test_valid_baseline_round_trips_and_separate_identities() -> None:
    spec = spec_fixture()
    permit = permit_fixture(spec)
    manifest = manifest_fixture(permit)
    receipt = receipt_fixture(manifest)
    for model in (
        spec,
        permit,
        RuntimePreparationInput(schema_version="runtime-preparation-input-v1", permit=permit),
        manifest,
        receipt,
    ):
        assert type(model).model_validate_json(model.model_dump_json()) == model
        assert type(model).model_json_schema()["additionalProperties"] is False
    assert type(spec.preparation_ref) is RuntimePreparationRef
    assert type(permit.permit_ref) is PreparationPermitRef
    assert type(manifest.manifest_ref) is RuntimePreparationManifestRef
    assert type(manifest.resource_ref) is ResourceRef
    assert spec.budgets.max_preparation_write_bytes != plan_fixture().limits.disk_write_bytes
    assert manifest.external_installed_dependencies == ()
    assert manifest.spec.profile.network.target_network == "DENY"


def test_nested_immutability_and_detachment() -> None:
    spec = spec_fixture()
    permit = permit_fixture(spec)
    manifest = manifest_fixture(permit)
    for model, field in (
        (spec, "node_id"),
        (spec.source, "manifest_size_bytes"),
        (spec.profile.network, "target_network"),
        (spec.profile.confinement, "required_features"),
        (spec.budgets, "max_processes"),
        (permit.boundary, "target_execution"),
        (manifest.environment, "pip_used"),
    ):
        with pytest.raises(ValidationError, match="frozen_instance"):
            setattr(model, field, None)
    payload = permit.model_dump(mode="json")
    restored = PreparationPermit.model_validate(payload)
    payload["spec"]["source"]["manifest_size_bytes"] = 999
    assert restored == permit


@pytest.mark.parametrize("ref", ["", "1bad", "bad space", "bad\\path"])
def test_preparation_refs_reject_invalid_values(ref: str) -> None:
    with pytest.raises(ValueError):
        RuntimePreparationRef(ref)
    with pytest.raises(ValueError):
        PreparationPermitRef(ref)
    with pytest.raises(ValueError):
        RuntimePreparationManifestRef(ref)


def test_cross_type_ref_is_rejected_before_serialization() -> None:
    data = spec_fixture().model_dump()
    data["preparation_ref"] = PreparationPermitRef("permit-wrong-kind")
    with pytest.raises(ValidationError):
        RuntimePreparationSpec.model_validate(data)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("plan_intent_sha256", ""),
        ("node_id", "bad node"),
        ("provider_version", "broken"),
        ("schema_version", "runtime-preparation-spec-v2"),
    ],
)
def test_spec_rejects_missing_or_invalid_authoritative_fields(field: str, invalid: str) -> None:
    data = spec_fixture().model_dump(mode="json")
    data[field] = invalid
    with pytest.raises(ValidationError):
        RuntimePreparationSpec.model_validate(data)
    data.pop(field)
    with pytest.raises(ValidationError):
        RuntimePreparationSpec.model_validate(data)


def test_baseline_forbidden_policies_and_actions_rejected() -> None:
    data = spec_fixture().model_dump(mode="json")
    for key in (
        "external_dependency_installation",
        "pip",
        "source_import",
        "entrypoint_execution",
    ):
        changed = spec_fixture().model_dump(mode="json")
        changed["profile"][key] = "ALLOW"
        with pytest.raises(ValidationError):
            RuntimePreparationSpec.model_validate(changed)
    data["profile"]["network"]["target_network"] = "ALLOW"
    with pytest.raises(ValidationError):
        RuntimePreparationSpec.model_validate(data)
    data = spec_fixture().model_dump(mode="json")
    data["profile"]["secrets"]["target_secret_grants"] = "ALLOW"
    with pytest.raises(ValidationError):
        RuntimePreparationSpec.model_validate(data)
    data = spec_fixture().model_dump(mode="json")
    data["allowed_actions"].append("EXECUTE_PLAN")
    with pytest.raises(ValidationError):
        RuntimePreparationSpec.model_validate(data)


def test_limits_and_confinement_cannot_be_unbounded_or_omitted() -> None:
    for field in PreparationBudgets.model_fields:
        data = spec_fixture().model_dump(mode="json")
        data["budgets"][field] = None
        with pytest.raises(ValidationError):
            RuntimePreparationSpec.model_validate(data)
    data = spec_fixture().model_dump(mode="json")
    data["profile"]["confinement"]["required_features"].pop()
    with pytest.raises(ValidationError):
        RuntimePreparationSpec.model_validate(data)
    data = spec_fixture().model_dump(mode="json")
    data["profile"]["confinement"] = {}
    with pytest.raises(ValidationError):
        RuntimePreparationSpec.model_validate(data)


def test_missing_source_and_profile_identity_fail_closed() -> None:
    data = spec_fixture().model_dump(mode="json")
    data["source"]["plan_source"].pop("raw_artifact_ref")
    with pytest.raises(ValidationError):
        RuntimePreparationSpec.model_validate(data)
    data = spec_fixture().model_dump(mode="json")
    data["profile"].pop("profile_id")
    with pytest.raises(ValidationError):
        RuntimePreparationSpec.model_validate(data)


def test_permit_policy_approval_bounds_and_no_execution_authority() -> None:
    permit = permit_fixture()
    assert permit.boundary.target_execution is False
    assert permit.boundary.arbitrary_command_execution is False
    assert not hasattr(permit, "execute")
    assert not hasattr(permit, "to_execution_authorization")
    assert not any("EXECUTE" in action.value for action in PreparationAction)
    data = permit.model_dump(mode="json")
    data["boundary"]["target_execution"] = True
    with pytest.raises(ValidationError):
        PreparationPermit.model_validate(data)
    data = permit.model_dump(mode="json")
    data["policy_decision"] = "REQUIRES_APPROVAL"
    with pytest.raises(ValidationError):
        PreparationPermit.model_validate(data)
    data["approval_decision_ref"] = "decision-approval"
    assert PreparationPermit.model_validate(data).approval_decision_ref == PlanDecisionRef(
        "decision-approval"
    )
    data["expires_at"] = (NOW + timedelta(days=2)).isoformat()
    with pytest.raises(ValidationError):
        PreparationPermit.model_validate(data)
    data = permit.model_dump(mode="json")
    data["spec_sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        PreparationPermit.model_validate(data)


def test_reason_categories_are_distinct_from_outcome() -> None:
    assert PreparationReasonCode.POLICY_DENIED.category is PreparationReasonCategory.AUTHORITY
    assert PreparationReasonCode.BUILD_UNSUPPORTED.category is PreparationReasonCategory.UNSUPPORTED
    assert (
        PreparationReasonCode.SOURCE_INTEGRITY_FAILURE.category
        is PreparationReasonCategory.INTEGRITY
    )
    assert (
        PreparationReasonCode.CONFINEMENT_UNAVAILABLE.category
        is PreparationReasonCategory.RUNTIME_PREREQUISITE
    )
    assert PreparationReasonCode.STORAGE_UNAVAILABLE.category is PreparationReasonCategory.RESOURCE
    assert (
        PreparationReasonCode.PREPARATION_INTERRUPTED.category is PreparationReasonCategory.RECOVERY
    )
    assert (
        PreparationReasonCode.PREPARATION_CANCELLED.category
        is PreparationReasonCategory.CANCELLATION
    )


def test_success_manifest_requires_empty_dependencies_and_proven_controls() -> None:
    manifest = manifest_fixture()
    data = manifest.model_dump(mode="json")
    data["external_installed_dependencies"] = ["requests"]
    with pytest.raises(ValidationError):
        RuntimePreparationManifest.model_validate(data)
    data = manifest.model_dump(mode="json")
    data["confinement"]["verified_features"].pop()
    with pytest.raises(ValidationError):
        RuntimePreparationManifest.model_validate(data)
    data = manifest.model_dump(mode="json")
    data["usage"]["temporary_bytes"] = manifest.spec.budgets.max_temporary_bytes + 1
    with pytest.raises(ValidationError):
        RuntimePreparationManifest.model_validate(data)
    data = manifest.model_dump(mode="json")
    data["environment"]["source_imported"] = True
    with pytest.raises(ValidationError):
        RuntimePreparationManifest.model_validate(data)
    data = manifest.model_dump(mode="json")
    data["reason_code"] = PreparationReasonCode.POLICY_DENIED
    with pytest.raises(ValidationError):
        RuntimePreparationManifest.model_validate(data)


def test_receipt_is_not_acceptance_and_rejects_unbound_output() -> None:
    receipt = receipt_fixture()
    assert "accepted" not in RuntimePreparationReceipt.model_fields
    assert "execution_authorization" not in RuntimePreparationReceipt.model_fields
    data = receipt.model_dump(mode="json")
    data["resource_ref"] = None
    with pytest.raises(ValidationError):
        RuntimePreparationReceipt.model_validate(data)
    data = receipt.model_dump(mode="json")
    data["schema_version"] = "runtime-preparation-receipt-v2"
    with pytest.raises(ValidationError):
        RuntimePreparationReceipt.model_validate(data)


def test_digests_are_distinct_and_sensitive_to_authority_fields() -> None:
    spec = spec_fixture()
    permit = permit_fixture(spec)
    manifest = manifest_fixture(permit)
    assert (
        len(
            {
                preparation_profile_digest(spec.profile),
                preparation_spec_fingerprint(spec),
                preparation_permit_digest(permit),
                preparation_manifest_digest(manifest),
            }
        )
        == 4
    )
    changes: tuple[dict[str, object], ...] = (
        {"plan_intent_sha256": "9" * 64},
        {"node_id": "node-other"},
        {"provider_version": "2.0.0"},
        {
            "source": spec.source.model_copy(
                update={
                    "plan_source": spec.source.plan_source.model_copy(
                        update={"raw_sha256": "9" * 64}
                    )
                }
            )
        },
        {"budgets": spec.budgets.model_copy(update={"max_processes": 3})},
        {"profile": spec.profile.model_copy(update={"profile_version": "2"})},
        {
            "profile": spec.profile.model_copy(
                update={
                    "confinement": spec.profile.confinement.model_copy(
                        update={"required_features": tuple(ConfinementFeature)[:-1]}
                    )
                }
            )
        },
    )
    for change in changes:
        modified_spec = spec.model_copy(update=change)
        assert preparation_spec_fingerprint(modified_spec) != preparation_spec_fingerprint(spec)
    assert preparation_spec_fingerprint(
        spec.model_copy(update={"preparation_ref": RuntimePreparationRef("preparation-other")})
    ) == preparation_spec_fingerprint(spec)
    for field, value in (
        ("policy_context_sha256", "8" * 64),
        ("approval_decision_ref", PlanDecisionRef("decision-other")),
        ("run_ref", CapabilityRunRef("run-other")),
    ):
        modified_permit = permit.model_copy(update={field: value})
        assert preparation_permit_digest(modified_permit) != preparation_permit_digest(permit)
    assert preparation_manifest_digest(
        manifest.model_copy(update={"resource_ref": ResourceRef("resource-other")})
    ) != preparation_manifest_digest(manifest)
    assert canonical_digest(spec.profile) == preparation_profile_digest(spec.profile)


def test_unknown_fields_and_versions_fail_closed() -> None:
    for model in (spec_fixture(), permit_fixture(), manifest_fixture(), receipt_fixture()):
        data = model.model_dump(mode="json")
        data["execution_authorization"] = "APPROVED"
        with pytest.raises(ValidationError, match="extra_forbidden"):
            type(model).model_validate(data)
        data.pop("execution_authorization")
        data["schema_version"] = "unknown-v99"
        with pytest.raises(ValidationError):
            type(model).model_validate(data)


def test_ref_types_and_timestamps_remain_json_safe() -> None:
    manifest = manifest_fixture()
    assert isinstance(manifest.started_at, datetime)
    assert manifest.started_at.tzinfo is UTC
    assert "synthetic-plaintext-never-serialized" not in manifest.model_dump_json()
    assert type(manifest.spec.plan_ref) is ExecutionPlanRef
    assert type(manifest.spec.mission_ref) is MissionRef
