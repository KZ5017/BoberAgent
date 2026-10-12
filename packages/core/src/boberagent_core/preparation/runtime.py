"""Core's intermediate E5 pump: current admission and Router, never E6 completion."""

from boberagent_contracts import (
    CapabilityRunStatus,
    PythonRuntimeAuthorityProjection,
    PythonRuntimeProfileIdentity,
    PythonRuntimeRequestBinding,
    RuntimePreparationRef,
    Sha256Digest,
    preparation_permit_digest,
    python_runtime_request_digest,
)
from boberagent_contracts.python_runtime import RuntimeCorrelation, RuntimeResourceRef
from boberagent_transport import MaterializationEvidence
from boberagent_transport.preparation_runtime import (
    PYTHON_RUNTIME_PROTOCOL_VERSION,
    PythonRuntimeAccepted,
    PythonRuntimeRejected,
    PythonRuntimeRequest,
    RuntimePreparationOperation,
    runtime_message_id,
)

from ..capabilities import CapabilityRegistrationClient
from .dispatch import CorePreparationDispatchService, PreparationDispatchError
from .models import PreparationLifecycle


class CorePythonRuntimeService:
    """Explicit pump over the existing preparation dispatch composition."""

    def __init__(self, dispatch: CorePreparationDispatchService) -> None:
        self._dispatch = dispatch

    async def exchange(
        self,
        ref: RuntimePreparationRef,
        *,
        materialization: MaterializationEvidence,
        operation: RuntimePreparationOperation,
        attempt_id: RuntimeCorrelation | None = None,
        resource_ref: RuntimeResourceRef | None = None,
        binding_sha256: Sha256Digest | None = None,
    ) -> PythonRuntimeAccepted:
        dispatch = self._dispatch
        current = dispatch._current(ref)
        permit = current.permit
        assert permit is not None
        node_id = permit.spec.node_id
        advertisement, _ = await CapabilityRegistrationClient(
            dispatch._transport, dispatch._registry
        ).refresh_node(node_id)
        current = dispatch._current(ref)
        if current.attempt.lifecycle is not PreparationLifecycle.DISPATCHED:
            raise PreparationDispatchError("PREPARATION_STATE_INELIGIBLE")
        provider = dispatch._router.select_provider(
            capability_id="runtime.prepare",
            operation="prepare",
            provider_id=current.attempt.context.request.provider_id,
            node_id=node_id,
        )
        if provider.implementation_version != permit.spec.provider_version:
            raise PreparationDispatchError("PREPARATION_PROVIDER_CHANGED")
        if PYTHON_RUNTIME_PROTOCOL_VERSION not in advertisement.preparation_runtime_versions:
            raise PreparationDispatchError("RUNTIME_PROTOCOL_UNSUPPORTED")
        if (
            await dispatch._transport.query_run_status(node_id, permit.run_ref)
            is not CapabilityRunStatus.QUEUED
        ):
            raise PreparationDispatchError("PREPARATION_DISPATCH_UNCERTAIN")
        raw = permit.spec.source.plan_source
        if (
            materialization.preparation_ref != ref
            or materialization.permit_ref != permit.permit_ref
            or materialization.run_ref != permit.run_ref
            or materialization.node_id != node_id
            or materialization.raw_artifact_ref != raw.raw_artifact_ref
            or materialization.raw_sha256 != raw.raw_sha256
            or materialization.manifest_artifact_ref != raw.manifest_artifact_ref
            or materialization.manifest_sha256 != raw.manifest_sha256
        ):
            raise PreparationDispatchError("MATERIALIZATION_IDENTITY_CONFLICT")
        if (
            operation
            in {
                RuntimePreparationOperation.PREPARE_RUNTIME,
                RuntimePreparationOperation.REVALIDATE_RUNTIME,
            }
            and attempt_id is None
        ):
            raise PreparationDispatchError("RUNTIME_ATTEMPT_ID_REQUIRED")
        authority = PythonRuntimeAuthorityProjection(
            permit=permit,
            binding=PythonRuntimeRequestBinding(
                schema_version="python-runtime-request-binding-v1",
                spec=permit.spec,
                permit_ref=permit.permit_ref,
                permit_sha256=preparation_permit_digest(permit),
                run_ref=permit.run_ref,
                materialization_id=materialization.materialization_id,
                source_tree_sha256=materialization.tree_sha256,
                entrypoint_sha256=permit.spec.entrypoint.entry_sha256,
                profile=PythonRuntimeProfileIdentity(
                    profile_id=permit.spec.profile.profile_id,
                    profile_version="1",
                    profile_sha256=permit.spec.profile_sha256,
                    runtime_provider="python-stdlib@1",
                    construction_version="python-stdlib@1",
                    layout_version="m20-e5-python-layout@1",
                ),
            ),
        )
        request = PythonRuntimeRequest(
            message_id=runtime_message_id(
                authority, operation, resource_ref, binding_sha256, attempt_id
            ),
            node_id=node_id,
            preparation_ref=ref,
            permit_ref=permit.permit_ref,
            permit_sha256=preparation_permit_digest(permit),
            run_ref=permit.run_ref,
            operation=operation,
            authority=authority,
            attempt_id=attempt_id,
            resource_ref=resource_ref,
            binding_sha256=binding_sha256,
            timestamp=dispatch._clock(),
        )
        response = await dispatch._transport.exchange_preparation_runtime(request)
        dispatch._current(ref)  # In-flight policy changes cannot yield accepted current authority.
        if isinstance(response, PythonRuntimeRejected):
            raise PreparationDispatchError(response.failure.reason_code.value)
        if (
            response.request_binding_sha256 != python_runtime_request_digest(authority.binding)
            or (resource_ref is not None and response.resource_ref != resource_ref)
            or (
                binding_sha256 is not None
                and response.current is not None
                and response.current.binding_sha256 != binding_sha256
            )
        ):
            raise PreparationDispatchError("RUNTIME_RESPONSE_IDENTITY_CONFLICT")
        return response
