"""Node-owned intermediate E5 pump. Disconnect never owns the worker lifetime."""

from __future__ import annotations

import asyncio

from boberagent_contracts import (
    DomainRef,
    PreparationAction,
    PreparationReasonCode,
    PythonProviderOperation,
    PythonRuntimeFailure,
    PythonRuntimeReason,
    python_runtime_binding_digest,
    python_runtime_request_digest,
)
from boberagent_transport.preparation_runtime import (
    PythonRuntimeAccepted,
    PythonRuntimeRejected,
    PythonRuntimeRequest,
    PythonRuntimeResponse,
    RuntimePreparationOperation,
)

from ..artifacts.spool import LocalArtifactSpool
from .python_distribution import digest_value
from .python_environment import EnvironmentFailure, PythonEnvironmentProvider
from .python_provenance import PythonProvenanceRepository, inspect_owned_interpreter
from .python_revalidation import PythonRevalidationRepository, revalidate_environment
from .resource_models import OperationState, ResourceOperation
from .resources import ResourceOwnershipError
from .service import NodePreparationService


class NodePythonRuntimeService:
    def __init__(self, provider: PythonEnvironmentProvider, source: NodePreparationService) -> None:
        self.provider, self.source = provider, source
        self.repository = PythonRevalidationRepository(provider)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def handle(
        self, request: PythonRuntimeRequest, *, principal: str, artifacts: LocalArtifactSpool
    ) -> PythonRuntimeResponse:
        resources = self.provider.repository.resources
        base = dict(
            request_message_id=request.message_id,
            node_id=request.node_id,
            preparation_ref=request.preparation_ref,
            permit_ref=request.permit_ref,
            permit_sha256=request.permit_sha256,
            run_ref=request.run_ref,
            timestamp=resources._now(),
        )
        try:
            async with self._lock:
                # Never reserve or quarantine on a mismatched Resource/status request.
                with resources._database.transaction() as session:
                    resources._admitted(session, request.authority.permit, principal)
                    resources._current(
                        request.authority.permit, resources_action(request.operation)
                    )
                if request.operation is RuntimePreparationOperation.PREPARE_RUNTIME:
                    reservation = resources.reserve(request.authority, principal_id=principal)
                    ref = reservation.resource_ref
                else:
                    if request.resource_ref is None:
                        raise EnvironmentFailure(PythonRuntimeReason.PYTHON_RUNTIME_UNAVAILABLE)
                    ref = request.resource_ref
                reservation = resources.load(ref)
                if reservation.request != request.authority.binding:
                    raise EnvironmentFailure(PythonRuntimeReason.RUNTIME_IDENTITY_CONFLICT)
                provenance = PythonProvenanceRepository(resources).history(ref)
                if request.resource_ref is not None and (
                    not provenance
                    or python_runtime_binding_digest(provenance[-1].binding)
                    != request.binding_sha256
                ):
                    raise EnvironmentFailure(PythonRuntimeReason.RUNTIME_IDENTITY_CONFLICT)
                if request.operation not in {
                    RuntimePreparationOperation.PREPARE_RUNTIME,
                    RuntimePreparationOperation.REVALIDATE_RUNTIME,
                    RuntimePreparationOperation.RUNTIME_STATUS,
                }:
                    raise EnvironmentFailure(PythonRuntimeReason.PYTHON_RUNTIME_UNAVAILABLE)
                # Only an authenticated, exact binding can trigger safety invalidation.
                # An unrelated/mismatched request must never poison another Resource.
                try:
                    self.source.verify_retained_source(reservation.request, principal=principal)
                except (ValueError, OSError):
                    resources.quarantine(ref, EnvironmentFailure().failure)
                    raise EnvironmentFailure() from None
                if request.operation is not RuntimePreparationOperation.RUNTIME_STATUS:
                    if request.attempt_id is None:
                        raise EnvironmentFailure(PythonRuntimeReason.RUNTIME_IDENTITY_CONFLICT)
                    construction = self.provider.repository.history(ref)
                    # Attempt labels are local to immutable authority, not globally unique.
                    correlation = digest_value((reservation.request_sha256, request.attempt_id))
                    operation_id = DomainRef("runtime-" + correlation)
                    operation = PythonProviderOperation.REVALIDATE
                    if request.operation is RuntimePreparationOperation.PREPARE_RUNTIME:
                        if construction is not None:
                            operation_id = construction.operation_id
                        else:
                            operation = (
                                PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT
                                if provenance
                                else PythonProviderOperation.INSPECT_INTERPRETER
                            )
                            operation_id = reservation.active_operation_id or DomainRef(
                                str(operation_id) + ("-construct" if provenance else "-inspect")
                            )
                    existing = next(
                        (o for o in resources.operations(ref) if o.operation_id == operation_id),
                        None,
                    )
                    if existing is None:
                        claim = resources.claim(
                            ref,
                            operation_id=operation_id,
                            operation=operation,
                            owner_token=DomainRef("owner-" + correlation),
                            principal_id=principal,
                            lease_seconds=320,
                        )
                        task = asyncio.create_task(self._run(request, claim, principal, artifacts))
                        self._tasks[str(operation_id)] = task
                        task.add_done_callback(self._discard_task)
                    elif (
                        existing.state is not OperationState.COMPLETED
                        and existing.state is not OperationState.ACTIVE
                    ):
                        raise EnvironmentFailure(PythonRuntimeReason.RUNTIME_QUARANTINED)
                construction = self.provider.repository.history(ref)
                current = self.repository.current(ref) if construction is not None else None
                history = self.repository.history(ref)
                operations = resources.operations(ref)
                latest = operations[-1] if operations else None
                return PythonRuntimeAccepted.model_validate(
                    dict(
                        base,
                        request_binding_sha256=python_runtime_request_digest(reservation.request),
                        resource_ref=ref,
                        current=current,
                        evidence=history[-1]
                        if history
                        else (provenance[-1] if provenance else None),
                        operation_id=None if latest is None else latest.operation_id,
                        operation_state=None if latest is None else latest.state.value,
                        construction_sha256=None
                        if construction is None
                        else digest_value(construction),
                    )
                )
        except (ValueError, KeyError, OSError, RuntimeError) as error:
            failure = getattr(error, "failure", None)
            if not isinstance(failure, PythonRuntimeFailure):
                failure = PythonRuntimeFailure(
                    reason_code=error.code
                    if isinstance(error, ResourceOwnershipError)
                    else PreparationReasonCode.PREPARED_CONTENT_MISMATCH,
                )
            return PythonRuntimeRejected.model_validate(dict(base, failure=failure))

    async def _run(
        self,
        request: PythonRuntimeRequest,
        claim: ResourceOperation,
        principal: str,
        artifacts: LocalArtifactSpool,
    ) -> None:
        resources = self.provider.repository.resources
        try:
            if claim.operation is PythonProviderOperation.INSPECT_INTERPRETER:
                await inspect_owned_interpreter(
                    self.provider.distribution,
                    self.provider.backend,
                    self.provider.backend_identity,
                    PythonProvenanceRepository(resources),
                    claim,
                    clock=resources._now,
                )
                claim = resources.claim(
                    claim.resource_ref,
                    operation_id=DomainRef(
                        str(claim.operation_id).removesuffix("-inspect") + "-construct"
                    ),
                    operation=PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT,
                    owner_token=claim.owner_token,
                    principal_id=principal,
                    lease_seconds=320,
                )
            if claim.operation is PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT:
                await self.provider.create_empty_environment(claim)
            else:
                await revalidate_environment(
                    self.repository,
                    claim,
                    verify_source=lambda: self.source.verify_retained_source(
                        request.authority.binding, principal=principal
                    ),
                    artifacts=artifacts,
                    clock=resources._now,
                )
        except BaseException as error:
            failure = getattr(error, "failure", None)
            if not isinstance(failure, PythonRuntimeFailure):
                failure = PythonRuntimeFailure(
                    reason_code=PreparationReasonCode.PREPARATION_INTERRUPTED,
                    runtime_reason=PythonRuntimeReason.RUNTIME_QUARANTINED,
                )
            resources.quarantine(claim.resource_ref, failure)
            if isinstance(error, asyncio.CancelledError):
                raise

    async def shutdown(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _discard_task(self, task: asyncio.Task[None]) -> None:
        for key, value in tuple(self._tasks.items()):
            if value is task:
                self._tasks.pop(key)


def resources_action(operation: RuntimePreparationOperation) -> PreparationAction:
    return (
        PreparationAction.CREATE_EMPTY_PYTHON_ENVIRONMENT
        if operation is RuntimePreparationOperation.PREPARE_RUNTIME
        else PreparationAction.VERIFY_PYTHON_ENVIRONMENT
    )
