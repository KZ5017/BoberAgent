"""E5-A exchanges only serializable claims, never executable requests."""

import json
from datetime import timedelta

import pytest
from boberagent_contracts import (
    PythonRuntimeFailure,
    PythonRuntimeReason,
    ResourceRef,
    python_runtime_binding_digest,
    python_runtime_request_digest,
)
from boberagent_transport import (
    MalformedMessage,
    PythonRuntimeAccepted,
    PythonRuntimeRejected,
    PythonRuntimeRequest,
    RuntimePreparationOperation,
    parse_python_runtime_request,
    parse_python_runtime_response,
    runtime_message_id,
)
from plan_test_fixtures import NOW
from python_runtime_test_fixtures import runtime_authority_fixture, runtime_evidence_fixture


def request_fixture(operation: RuntimePreparationOperation) -> PythonRuntimeRequest:
    authority = runtime_authority_fixture()
    is_resource = operation in {
        RuntimePreparationOperation.RUNTIME_STATUS,
        RuntimePreparationOperation.REVALIDATE_RUNTIME,
        RuntimePreparationOperation.RELEASE_RUNTIME,
    }
    evidence = runtime_evidence_fixture()
    ref = evidence.binding.resource_ref if is_resource else None
    digest = python_runtime_binding_digest(evidence.binding) if is_resource else None
    return PythonRuntimeRequest(
        message_id=runtime_message_id(authority, operation, ref, digest),
        node_id=authority.binding.spec.node_id,
        preparation_ref=authority.binding.spec.preparation_ref,
        permit_ref=authority.permit.permit_ref,
        permit_sha256=authority.binding.permit_sha256,
        run_ref=authority.permit.run_ref,
        operation=operation,
        authority=authority,
        resource_ref=ref,
        binding_sha256=digest,
        timestamp=NOW,
    )


@pytest.mark.parametrize("operation", list(RuntimePreparationOperation))
def test_all_closed_operations_round_trip(operation: RuntimePreparationOperation) -> None:
    request = request_fixture(operation)
    assert parse_python_runtime_request(request.model_dump_json().encode()) == request
    assert request.model_json_schema()["additionalProperties"] is False
    replay = request.model_copy(update={"timestamp": NOW + timedelta(seconds=1)})
    assert replay.message_id == request.message_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol_version", "preparation-runtime-v2"),
        ("operation", "EXECUTE_PLAN"),
        ("message_id", "message-wrong"),
        ("preparation_ref", "preparation-wrong"),
        ("permit_ref", "permit-wrong"),
        ("permit_sha256", "0" * 64),
        ("run_ref", "run-wrong"),
        ("node_id", "node-wrong"),
        ("argv", ["python", "-c", "source"]),
        ("shell", "source.sh"),
        ("host_path", "/tmp/runtime"),
        ("resource_ref", "resource-selected-by-caller"),
    ],
)
def test_invalid_or_executable_request_rejected(field: str, value: object) -> None:
    data = request_fixture(RuntimePreparationOperation.PREPARE_RUNTIME).model_dump(mode="json")
    data[field] = value
    with pytest.raises(MalformedMessage):
        parse_python_runtime_request(json.dumps(data).encode())


@pytest.mark.parametrize("field", ["resource_ref", "binding_sha256", "permit_sha256", "authority"])
def test_resource_operations_require_all_pins(field: str) -> None:
    data = request_fixture(RuntimePreparationOperation.RUNTIME_STATUS).model_dump(mode="json")
    del data[field]
    with pytest.raises(MalformedMessage):
        parse_python_runtime_request(json.dumps(data).encode())


def test_responses_round_trip_and_correlate_evidence() -> None:
    request = request_fixture(RuntimePreparationOperation.PREPARE_RUNTIME)
    evidence = runtime_evidence_fixture()
    accepted = PythonRuntimeAccepted(
        request_message_id=request.message_id,
        node_id=request.node_id,
        preparation_ref=request.preparation_ref,
        permit_ref=request.permit_ref,
        permit_sha256=request.permit_sha256,
        run_ref=request.run_ref,
        timestamp=NOW,
        request_binding_sha256=python_runtime_request_digest(request.authority.binding),
        resource_ref=evidence.binding.resource_ref,
        current=None,
        evidence=evidence,
    )
    detail = PythonRuntimeReason.PYTHON_RUNTIME_UNAVAILABLE
    rejected = PythonRuntimeRejected(
        request_message_id=request.message_id,
        node_id=request.node_id,
        preparation_ref=request.preparation_ref,
        permit_ref=request.permit_ref,
        permit_sha256=request.permit_sha256,
        run_ref=request.run_ref,
        timestamp=NOW,
        failure=PythonRuntimeFailure(reason_code=detail.preparation_reason, runtime_reason=detail),
    )
    for response in (accepted, rejected):
        assert parse_python_runtime_response(response.model_dump_json().encode()) == response
    data = accepted.model_dump(mode="json")
    data["resource_ref"] = str(ResourceRef("resource-wrong"))
    with pytest.raises(MalformedMessage):
        parse_python_runtime_response(json.dumps(data).encode())
    with pytest.raises(MalformedMessage):
        parse_python_runtime_response(b'{"message_type":"unknown"}')


def test_no_source_or_secret_payload_in_wire_contract() -> None:
    schema = PythonRuntimeRequest.model_json_schema()
    properties = schema["properties"]
    assert not set(properties) & {
        "argv",
        "command",
        "environment",
        "source",
        "secret",
        "execution_plan",
    }
