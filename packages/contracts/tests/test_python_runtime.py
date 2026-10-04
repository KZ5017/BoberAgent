"""E5-A validation describes future facts; it produces no Resource or authority."""

import json

import pytest
from boberagent_contracts import (
    AccessMode,
    PythonProviderPhase,
    PythonResourceState,
    PythonRuntimeAuthorityProjection,
    PythonRuntimeBinding,
    PythonRuntimeCurrentState,
    PythonRuntimeEvidence,
    PythonRuntimeFailure,
    PythonRuntimeReason,
    PythonRuntimeValidity,
    ResourceRef,
    python_runtime_binding_digest,
    python_runtime_evidence_digest,
    python_runtime_request_digest,
)
from plan_test_fixtures import NOW
from pydantic import BaseModel, ValidationError
from python_runtime_test_fixtures import (
    runtime_authority_fixture,
    runtime_binding_fixture,
    runtime_evidence_fixture,
)


def test_versioned_provider_descriptor_round_trip() -> None:
    from boberagent_contracts import DomainRef, ResourceDescriptor
    from plan_test_fixtures import NOW

    authority = runtime_authority_fixture()
    descriptor = ResourceDescriptor(
        resource_id=runtime_binding_fixture().resource_ref,
        resource_type="python_runtime",
        provider="python-stdlib@1",
        state="CREATING",
        owner_ref=DomainRef(str(authority.permit.spec.mission_ref)),
        created_by_run=authority.permit.run_ref,
        created_at=NOW,
        access_modes=(AccessMode.EXCLUSIVE,),
    )
    assert ResourceDescriptor.model_validate_json(descriptor.model_dump_json()) == descriptor
    for invalid in ("/host/provider", "python@", "python@1@2", "python provider"):
        with pytest.raises(ValidationError):
            ResourceDescriptor.model_validate({**descriptor.model_dump(), "provider": invalid})


def test_round_trip_schemas_and_nested_immutable_claims() -> None:
    for model in (
        runtime_authority_fixture(),
        runtime_binding_fixture(),
        runtime_evidence_fixture(),
    ):
        assert type(model).model_validate_json(model.model_dump_json()) == model
        assert type(model).model_json_schema()["additionalProperties"] is False
        _assert_frozen(model, next(iter(type(model).model_fields)))
    binding = runtime_binding_fixture()
    for nested in (
        binding.request,
        binding.request.spec.profile,
        binding.interpreter,
        binding.backend,
    ):
        _assert_frozen(nested, next(iter(type(nested).model_fields)))


def _assert_frozen(model: BaseModel, field: str) -> None:
    with pytest.raises(ValidationError, match="frozen_instance"):
        setattr(model, field, "changed")


@pytest.mark.parametrize("field", ["preparation_ref", "mission_ref", "plan_ref", "node_id"])
def test_authority_rejects_wrong_or_missing_spec_binding(field: str) -> None:
    data = runtime_authority_fixture().model_dump(mode="json")
    data["binding"]["spec"][field] = "wrong-ref"
    with pytest.raises(ValidationError):
        PythonRuntimeAuthorityProjection.model_validate_json(json.dumps(data))
    del data["binding"]["spec"][field]
    with pytest.raises(ValidationError):
        PythonRuntimeAuthorityProjection.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("field", ["permit_ref", "permit_sha256", "run_ref"])
def test_authority_rejects_wrong_or_missing_permit_binding(field: str) -> None:
    data = runtime_authority_fixture().model_dump(mode="json")
    data["binding"][field] = "0" * 64 if field.endswith("sha256") else "wrong-ref"
    with pytest.raises(ValidationError):
        PythonRuntimeAuthorityProjection.model_validate_json(json.dumps(data))
    del data["binding"][field]
    with pytest.raises(ValidationError):
        PythonRuntimeAuthorityProjection.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "path", ["", "/tmp/runtime", "C:\\venv", "C:/venv", "workspace/runtime", "bad ref"]
)
def test_resource_ref_rejects_invalid_and_host_paths(path: str) -> None:
    data = runtime_binding_fixture().model_dump(mode="json")
    data["resource_ref"] = path
    with pytest.raises(ValidationError):
        PythonRuntimeBinding.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("profile", "profile_version", "2"),
        ("profile", "profile_id", "python-3.13"),
        ("profile", "construction_version", "python-stdlib@2"),
        ("profile", "profile_sha256", "0" * 64),
        ("", "schema_version", "python-runtime-request-binding-v2"),
        ("", "entrypoint_sha256", "0" * 64),
        ("", "materialization_id", "/tmp/materialized"),
    ],
)
def test_unsupported_profile_or_inconsistent_source_fails_closed(
    section: str, field: str, value: str
) -> None:
    data = runtime_authority_fixture().model_dump(mode="json")
    target = data["binding"][section] if section else data["binding"]
    target[field] = value
    with pytest.raises(ValidationError):
        PythonRuntimeAuthorityProjection.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "field,value",
    [("python_version", "3.13.7"), ("registry_tool", "python3"), ("platform", "windows")],
)
def test_interpreter_has_no_fallback(field: str, value: str) -> None:
    data = runtime_binding_fixture().model_dump(mode="json")
    data["interpreter"]["summary"][field] = value
    with pytest.raises(ValidationError):
        PythonRuntimeBinding.model_validate_json(json.dumps(data))


def test_binding_digest_stability_and_authority_sensitive_changes() -> None:
    original = runtime_binding_fixture()
    digest = python_runtime_binding_digest(original)
    assert digest == python_runtime_binding_digest(
        PythonRuntimeBinding.model_validate_json(original.model_dump_json())
    )
    # Pure historical binding can differ, but a changed request is never admitted by
    # the old authority projection. Every meaningful pin participates in the digest.
    for section, field, value in (
        ("request", "materialization_id", "materialization:other"),
        ("request", "source_tree_sha256", "0" * 64),
        ("request", "permit_sha256", "0" * 64),
        ("spec", "node_id", "node-other"),
        ("spec", "provider_version", "2.0.0"),
        ("source", "raw_sha256", "0" * 64),
        ("interpreter", "closure_sha256", "0" * 64),
        ("backend", "profile_sha256", "0" * 64),
    ):
        data = original.model_dump(mode="json")
        target = (
            data[section]
            if section in {"request", "interpreter", "backend"}
            else (
                data["request"]["spec"]
                if section == "spec"
                else data["request"]["spec"]["source"]["plan_source"]
            )
        )
        target[field] = value
        changed = PythonRuntimeBinding.model_validate_json(json.dumps(data))
        assert python_runtime_binding_digest(changed) != digest
    assert python_runtime_request_digest(original.request) != digest


@pytest.mark.parametrize("detail", list(PythonRuntimeReason))
def test_reason_round_trip_and_category_mapping(detail: PythonRuntimeReason) -> None:
    failure = PythonRuntimeFailure(reason_code=detail.preparation_reason, runtime_reason=detail)
    assert PythonRuntimeFailure.model_validate_json(failure.model_dump_json()) == failure
    data = failure.model_dump(mode="json")
    data["reason_code"] = "POLICY_DENIED"
    with pytest.raises(ValidationError):
        PythonRuntimeFailure.model_validate_json(json.dumps(data))


def test_current_validity_is_separate_and_does_not_authorize_execution() -> None:
    state = PythonRuntimeCurrentState(
        resource_ref=ResourceRef("resource-test"),
        binding_sha256=python_runtime_binding_digest(runtime_binding_fixture()),
        state=PythonResourceState.READY,
        phase=PythonProviderPhase.PUBLISHED,
        validity=PythonRuntimeValidity.UNCHECKED,
    )
    assert not hasattr(runtime_binding_fixture(), "state")
    assert not hasattr(state, "execution_authorized")
    assert not hasattr(state, "execute")
    data = state.model_dump(mode="json")
    data["validity"] = "VALID"
    with pytest.raises(ValidationError):
        PythonRuntimeCurrentState.model_validate_json(json.dumps(data))
    data.update(checked_at=NOW.isoformat(), boot_generation="boot-test")
    checked = PythonRuntimeCurrentState.model_validate_json(json.dumps(data))
    assert checked.validity is PythonRuntimeValidity.VALID
    data["execution_authorized"] = True
    with pytest.raises(ValidationError):
        PythonRuntimeCurrentState.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("enforcement", "verified_features", ["NO_SUBPROCESS_NETWORK"]),
        ("enforcement", "passed_probes", []),
        ("enforcement", "pids_limit_events", 1),
        ("enforcement", "oom_events", 1),
        ("enforcement", "descendants_empty", False),
        ("enforcement", "effective_process_limit", "2"),
        ("enforcement", "effective_process_limit", 100),
        ("enforcement", "effective_memory_bytes", 2**40),
        ("enforcement", "process_mechanism", "RLIMIT_NPROC"),
        ("enforcement", "cgroup_path", "/sys/fs/cgroup/test"),
        ("environment", "pip_used", True),
        ("environment", "external_installed_dependencies", ["requests"]),
        ("environment", "copied_executable_sha256", "0" * 64),
        ("non_actions", "source_imported", True),
        ("non_actions", "source_imported", 0),
        ("non_actions", "target_secret_grants", ["secret-test"]),
        ("non_actions", "preparation_network", "ALLOW"),
        ("aggregate_usage", "peak_memory_bytes", 2**40),
        ("e5_usage", "preparation_write_bytes", 9999),
        ("", "schema_version", "PythonRuntimeEvidence-v2"),
        ("", "failure", {"reason_code": "POLICY_DENIED"}),
        ("", "environment", None),
        ("", "monotonic_duration_milliseconds", 99_000),
        ("", "argv", ["python", "-c", "print(1)"]),
    ],
)
def test_evidence_rejects_unknown_unverified_or_unsafe_claims(
    section: str, field: str, value: object
) -> None:
    data = runtime_evidence_fixture().model_dump(mode="json")
    target = data[section] if section else data
    target[field] = value
    with pytest.raises(ValidationError):
        PythonRuntimeEvidence.model_validate_json(json.dumps(data))


def test_evidence_digest_set_order_and_immutability() -> None:
    evidence = runtime_evidence_fixture()
    data = evidence.model_dump(mode="json")
    data["enforcement"]["verified_features"].reverse()
    data["enforcement"]["passed_probes"].reverse()
    restored = PythonRuntimeEvidence.model_validate_json(json.dumps(data))
    assert python_runtime_evidence_digest(evidence) == python_runtime_evidence_digest(restored)
    assert isinstance(evidence, BaseModel)
    with pytest.raises(ValidationError, match="frozen_instance"):
        evidence.verification = "REJECTED"
