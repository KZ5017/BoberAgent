"""E3 Core composition: route one reserved Run, then import two exact Core Artifacts."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime

from boberagent_contracts import (
    ArtifactRef,
    AssetRef,
    CapabilityInvocation,
    CapabilityRun,
    CapabilityRunStatus,
    RuntimePreparationInput,
    RuntimePreparationRef,
)
from boberagent_contracts.plan_values import NetworkTarget
from boberagent_transport import (
    MAX_IMPORT_CHUNK_BYTES,
    PREPARATION_IMPORT_PROTOCOL_VERSION,
    AssetProjection,
    ImportChunk,
    ImportCompleted,
    ImportFinalize,
    ImportReady,
    ImportRejected,
    ImportStart,
    InvocationDelivery,
    MissionProjection,
    PreparationTransport,
    import_message_id,
    preparation_import_id,
)

from boberagent_core.artifacts import CoreArtifactService
from boberagent_core.capabilities import (
    CapabilityRegistrationClient,
    CapabilityRegistry,
    CapabilityRouter,
)
from boberagent_core.clock import utc_now
from boberagent_core.models import ArtifactContentState
from boberagent_core.persistence import CoreDatabase

from .import_repository import ImportProgressState, PreparationImportProgress
from .models import PreparationAdmission, PreparationLifecycle
from .service import CoreRuntimePreparationAdmissionService


class PreparationDispatchError(ValueError):
    """Typed E3 stop; never a PoC execution result or implicit retry permission."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CorePreparationDispatchService:
    """Explicit pump; source bytes move only after current Core and Node admission."""

    def __init__(
        self,
        database: CoreDatabase,
        admission: CoreRuntimePreparationAdmissionService,
        registry: CapabilityRegistry,
        router: CapabilityRouter,
        transport: PreparationTransport,
        artifacts: CoreArtifactService,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._database = database
        self._admission = admission
        self._registry = registry
        self._router = router
        self._transport = transport
        self._artifacts = artifacts
        self._clock = clock

    async def dispatch_and_import(
        self, ref: RuntimePreparationRef, *, chunk_size: int = 256 * 1024
    ) -> tuple[PreparationImportProgress, PreparationImportProgress]:
        if not 1 <= chunk_size <= MAX_IMPORT_CHUNK_BYTES:
            raise PreparationDispatchError("IMPORT_CHUNK_LIMIT_INVALID")
        historical = self._admission.get_attempt(ref)
        if historical is None:
            raise PreparationDispatchError("PREPARATION_NOT_FOUND")
        node_id = historical.context.request.node_id
        advertisement, _ = await CapabilityRegistrationClient(
            self._transport, self._registry
        ).refresh_node(node_id)
        if PREPARATION_IMPORT_PROTOCOL_VERSION not in advertisement.preparation_import_versions:
            raise PreparationDispatchError("PREPARATION_PROTOCOL_UNSUPPORTED")
        current = self._current(ref)
        attempt = current.attempt
        permit = current.permit
        assert permit is not None and attempt.reserved_run_ref is not None
        provider = self._router.select_provider(
            capability_id="runtime.prepare",
            operation="prepare",
            provider_id=attempt.context.request.provider_id,
            node_id=node_id,
        )
        if provider.implementation_version != permit.spec.provider_version:
            raise PreparationDispatchError("PREPARATION_PROVIDER_CHANGED")
        source = permit.spec.source
        pins = (
            (
                source.plan_source.raw_artifact_ref,
                source.plan_source.raw_sha256,
                source.plan_source.raw_size_bytes,
            ),
            (
                source.plan_source.manifest_artifact_ref,
                source.plan_source.manifest_sha256,
                source.manifest_size_bytes,
            ),
        )
        for artifact_ref, sha256, size in pins:
            record = self._artifacts.get(artifact_ref)
            if (
                record is None
                or record.content_state is not ArtifactContentState.AVAILABLE
                or record.descriptor.sha256 != sha256
                or record.descriptor.size_bytes != size
                or not self._artifacts.content_available(artifact_ref)
            ):
                raise PreparationDispatchError("CORE_ARTIFACT_UNAVAILABLE")
        if attempt.lifecycle is PreparationLifecycle.REQUESTED:
            delivery = self._delivery(current)
            with self._database.unit_of_work() as work:
                fresh = work.runtime_preparations.get(ref)
                if fresh is None or fresh.lifecycle is not PreparationLifecycle.REQUESTED:
                    raise PreparationDispatchError("PREPARATION_DISPATCH_CONFLICT")
                work.runs.add(
                    CapabilityRun(
                        run_id=permit.run_ref,
                        capability_id="runtime.prepare",
                        operation="prepare",
                        mission_ref=permit.spec.mission_ref,
                        status=CapabilityRunStatus.QUEUED,
                        created_at=self._clock(),
                    )
                )
                work.runtime_preparations.mark_dispatched(
                    ref, expected_revision=fresh.revision, updated_at=self._clock()
                )
            # A failed/uncertain submission is deliberately not replayed automatically.
            await self._router.dispatch(
                invocation=delivery.invocation, delivery=delivery, provider=provider
            )
        elif attempt.lifecycle is PreparationLifecycle.DISPATCHED:
            state = await self._transport.query_run_status(node_id, permit.run_ref)
            if state is None:
                raise PreparationDispatchError("PREPARATION_DISPATCH_UNCERTAIN")
        else:
            raise PreparationDispatchError("PREPARATION_STATE_INELIGIBLE")
        progress = []
        for artifact_ref, sha256, size in pins:
            self._current(ref)  # Recheck D/Node/permit before each byte stream.
            progress.append(
                await self._import_one(
                    current,
                    artifact_ref=artifact_ref,
                    sha256=sha256,
                    size=size,
                    chunk_size=chunk_size,
                )
            )
        return progress[0], progress[1]

    def _current(self, ref: RuntimePreparationRef) -> PreparationAdmission:
        admission = self._admission.current_admission(ref)
        if admission is None or not admission.current_applicable or admission.permit is None:
            raise PreparationDispatchError("PREPARATION_AUTHORITY_STALE")
        return admission

    def _delivery(self, admission: PreparationAdmission) -> InvocationDelivery:
        permit = admission.permit
        assert permit is not None
        with self._database.unit_of_work() as work:
            mission = work.missions.get(permit.spec.mission_ref)
            plan_record = work.execution_plans.get(permit.spec.plan_ref)
            if mission is None or plan_record is None:
                raise PreparationDispatchError("PREPARATION_CONTEXT_MISSING")
            target = plan_record.plan.target
            assets: tuple[AssetProjection, ...] = ()
            allowed_assets: tuple[AssetRef, ...] = ()
            allowed_addresses: tuple[str, ...] = ()
            if isinstance(target, NetworkTarget):
                asset = work.assets.get(target.asset_ref)
                if asset is None or asset.mission_ref != mission.mission_ref:
                    raise PreparationDispatchError("PREPARATION_TARGET_STALE")
                assets = (
                    AssetProjection(
                        asset_ref=asset.asset_ref,
                        primary_address=asset.primary_address,
                        addresses=(asset.primary_address,),
                        metadata=asset.metadata,
                    ),
                )
                allowed_assets = (asset.asset_ref,)
                allowed_addresses = (target.address,)
        invocation = CapabilityInvocation(
            run_id=permit.run_ref,
            capability_id="runtime.prepare",
            operation="prepare",
            mission_ref=permit.spec.mission_ref,
            inputs=RuntimePreparationInput(
                schema_version="runtime-preparation-input-v1", permit=permit
            ).model_dump(mode="json"),
        )
        return InvocationDelivery(
            invocation=invocation,
            mission=MissionProjection(mission_ref=mission.mission_ref, name=mission.name),
            allowed_assets=allowed_assets,
            allowed_addresses=allowed_addresses,
            assets=assets,
            secret_grants=(),
        )

    async def _import_one(
        self,
        admission: PreparationAdmission,
        *,
        artifact_ref: ArtifactRef,
        sha256: str,
        size: int,
        chunk_size: int,
    ) -> PreparationImportProgress:
        permit = admission.permit
        assert permit is not None
        ref = admission.attempt.preparation_ref
        node_id = permit.spec.node_id
        import_id = preparation_import_id(permit.permit_ref, artifact_ref)
        start = ImportStart(
            node_id=node_id,
            preparation_ref=ref,
            permit_ref=permit.permit_ref,
            run_ref=permit.run_ref,
            import_id=import_id,
            artifact_ref=artifact_ref,
            message_id=import_message_id(import_id, "start"),
            sha256=sha256,
            size_bytes=size,
            timestamp=self._clock(),
        )
        response = await self._transport.exchange_preparation_import(start)
        if isinstance(response, ImportRejected):
            self._record(
                import_id,
                ref,
                artifact_ref,
                sha256,
                size,
                0,
                ImportProgressState.FAILED,
                response.code,
            )
            raise PreparationDispatchError(response.code)
        if isinstance(response, ImportCompleted):
            return self._accepted(import_id, ref, artifact_ref, sha256, size, response)
        offset = response.next_offset
        self._record(
            import_id, ref, artifact_ref, sha256, size, offset, ImportProgressState.IN_PROGRESS
        )
        with self._artifacts.open_content(artifact_ref) as stream:
            stream.seek(offset)
            while offset < size:
                self._current(ref)
                data = stream.read(min(chunk_size, size - offset))
                if not data:
                    raise PreparationDispatchError("CORE_ARTIFACT_INTERRUPTED")
                chunk = ImportChunk(
                    node_id=node_id,
                    preparation_ref=ref,
                    permit_ref=permit.permit_ref,
                    run_ref=permit.run_ref,
                    import_id=import_id,
                    artifact_ref=artifact_ref,
                    message_id=import_message_id(import_id, f"chunk:{offset}"),
                    offset=offset,
                    data=data,
                    chunk_sha256=hashlib.sha256(data).hexdigest(),
                    timestamp=self._clock(),
                )
                reply = await self._transport.exchange_preparation_import(chunk)
                if isinstance(reply, ImportRejected):
                    self._record(
                        import_id,
                        ref,
                        artifact_ref,
                        sha256,
                        size,
                        offset,
                        ImportProgressState.FAILED,
                        reply.code,
                    )
                    raise PreparationDispatchError(reply.code)
                if not isinstance(reply, ImportReady) or reply.next_offset != offset + len(data):
                    raise PreparationDispatchError("IMPORT_CURSOR_CONFLICT")
                offset = reply.next_offset
                self._record(
                    import_id,
                    ref,
                    artifact_ref,
                    sha256,
                    size,
                    offset,
                    ImportProgressState.IN_PROGRESS,
                )
        self._current(ref)  # Final publication still requires current Core authority.
        finalize = ImportFinalize(
            node_id=node_id,
            preparation_ref=ref,
            permit_ref=permit.permit_ref,
            run_ref=permit.run_ref,
            import_id=import_id,
            artifact_ref=artifact_ref,
            message_id=import_message_id(import_id, "finalize"),
            timestamp=self._clock(),
        )
        reply = await self._transport.exchange_preparation_import(finalize)
        if isinstance(reply, ImportRejected):
            self._record(
                import_id,
                ref,
                artifact_ref,
                sha256,
                size,
                offset,
                ImportProgressState.FAILED,
                reply.code,
            )
            raise PreparationDispatchError(reply.code)
        if not isinstance(reply, ImportCompleted):
            raise PreparationDispatchError("IMPORT_FINALIZE_UNCONFIRMED")
        return self._accepted(import_id, ref, artifact_ref, sha256, size, reply)

    def _accepted(
        self,
        import_id: object,
        ref: RuntimePreparationRef,
        artifact_ref: ArtifactRef,
        sha256: str,
        size: int,
        response: ImportCompleted,
    ) -> PreparationImportProgress:
        from boberagent_transport import PreparationImportId

        if response.sha256 != sha256 or response.size_bytes != size:
            raise PreparationDispatchError("IMPORT_ACK_IDENTITY_MISMATCH")
        assert isinstance(import_id, PreparationImportId)
        return self._record(
            import_id, ref, artifact_ref, sha256, size, size, ImportProgressState.VERIFIED
        )

    def _record(
        self,
        import_id: object,
        ref: RuntimePreparationRef,
        artifact_ref: ArtifactRef,
        sha256: str,
        size: int,
        received: int,
        state: ImportProgressState,
        error_code: str | None = None,
    ) -> PreparationImportProgress:
        from boberagent_transport import PreparationImportId

        assert isinstance(import_id, PreparationImportId)
        with self._database.unit_of_work() as work:
            return work.preparation_imports.record(
                import_id=import_id,
                preparation_ref=ref,
                artifact_ref=artifact_ref,
                sha256=sha256,
                size_bytes=size,
                received_bytes=received,
                state=state,
                updated_at=self._clock(),
                error_code=error_code,
            )
