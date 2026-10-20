"""E6 SDK adapter. Read exact retained E4/E5 facts; never construct/revalidate/execute."""

from uuid import uuid4

from boberagent_contracts import (
    CapabilityRunStatus,
    ConfinementEvidence,
    FixedEnvironmentEvidence,
    MaterializationEvidence,
    PreparationAction,
    PreparationOutcome,
    PreparationPermit,
    PreparationUsage,
    PythonEnvironmentEvidence,
    RuntimePreparationInput,
    RuntimePreparationManifest,
    RuntimePreparationManifestRef,
    RuntimePreparationReceipt,
    preparation_permit_digest,
    python_runtime_binding_digest,
    python_runtime_evidence_digest,
)
from boberagent_sdk import DependencyError
from sqlalchemy import select

from ..artifacts import LocalArtifactSpool
from ..persistence.orm import PythonResourceRow, RunRow
from .python_distribution import digest_value
from .python_revalidation import _FIELDS
from .runtime_service import NodePythonRuntimeService


class NodePreparationCompletionService:
    def __init__(
        self,
        runtime: NodePythonRuntimeService,
        principal: str,
        artifacts: LocalArtifactSpool,
        *,
        permit: PreparationPermit,
    ) -> None:
        self.runtime, self.principal, self.artifacts = runtime, principal, artifacts
        self._permit = permit

    def ready(self, request: RuntimePreparationInput) -> bool:
        """Only an existing current VALID Resource makes a queued replay executable."""
        self._require_binding(request)
        resources = self.runtime.provider.repository.resources
        with resources._database.transaction() as session:
            detail = session.scalar(
                select(PythonResourceRow).where(
                    PythonResourceRow.permit_id == str(request.permit.permit_ref)
                )
            )
            if detail is None:
                return False
            ref = resources._snapshot(session, detail).resource_ref
        current = self.runtime.repository.current(ref)
        return current.validity.value == "VALID" and current.state.value == "READY"

    async def prepare_runtime(self, request: RuntimePreparationInput) -> RuntimePreparationReceipt:
        self._require_binding(request)
        permit = request.permit
        resources = self.runtime.provider.repository.resources
        with resources._database.transaction() as session:
            resources._admitted(
                session, permit, self.principal, run_status=CapabilityRunStatus.RUNNING
            )
            resources._current(permit, PreparationAction.WRITE_PREPARATION_EVIDENCE)
            row = session.scalar(
                select(PythonResourceRow).where(
                    PythonResourceRow.permit_id == str(permit.permit_ref)
                )
            )
            if row is None or row.active_operation_id is not None:
                raise DependencyError("No quiescent prepared Resource")
            reservation = resources._snapshot(session, row)
            source = resources._materialization(session, reservation.request)
            run = session.get(RunRow, str(permit.run_ref))
            assert run is not None
            started = run.created_at
        current = self.runtime.repository.current(
            reservation.resource_ref,
            run_status=CapabilityRunStatus.RUNNING,
        )
        history = self.runtime.repository.history(reservation.resource_ref)
        construction = self.runtime.provider.repository.history(reservation.resource_ref)
        if not history or construction is None:
            raise DependencyError("Current retained runtime evidence unavailable")
        evidence = history[-1]
        if (
            current.validity.value != "VALID"
            or current.state.value != "READY"
            or current.phase.value != "PUBLISHED"
            or current.failure is not None
            or current.boot_generation != resources._boot
            or evidence.enforcement is None
            or evidence.enforcement.boot_generation != current.boot_generation
            or evidence.binding.request != reservation.request
            or evidence.binding.request.spec != permit.spec
            or evidence.verification != "VERIFIED"
            or evidence.failure is not None
            or evidence.environment is None
            or evidence.environment != construction.environment
            or not evidence.evidence_artifact_refs
        ):
            raise DependencyError("Runtime is not currently verified for this preparation")
        self.runtime.source.verify_retained_source(reservation.request, principal=self.principal)
        ledger = {
            item.category: item.committed for item in resources.budget(reservation.resource_ref)
        }
        usage = PreparationUsage(**{field: ledger[key] for key, field in _FIELDS.items()})
        if usage != evidence.aggregate_usage:
            raise DependencyError("Retained aggregate accounting conflicts with E5 evidence")
        backend, env, non_actions = (
            evidence.binding.backend,
            evidence.environment,
            evidence.non_actions,
        )
        manifest = RuntimePreparationManifest(
            schema_version="runtime-preparation-manifest-v1",
            manifest_ref=RuntimePreparationManifestRef(f"preparation-manifest-{uuid4().hex}"),
            spec=permit.spec,
            run_ref=permit.run_ref,
            permit_ref=permit.permit_ref,
            permit_sha256=preparation_permit_digest(permit),
            resource_ref=reservation.resource_ref,
            workspace_correlation=reservation.workspace_correlation,
            materialization=MaterializationEvidence(
                verified=True,
                file_count=source.file_count,
                total_bytes=source.materialized_bytes,
                tree_sha256=source.tree_sha256,
                entrypoint_sha256=reservation.request.entrypoint_sha256,
            ),
            interpreter=evidence.binding.interpreter.summary,
            environment=PythonEnvironmentEvidence(
                system_site_packages=env.system_site_packages,
                pip_bootstrapped=env.pip_bootstrapped,
                pip_used=env.pip_used,
                source_imported=non_actions.source_imported,
                source_compiled=non_actions.source_compiled,
                entrypoint_executed=non_actions.entrypoint_executed,
            ),
            external_installed_dependencies=env.external_installed_dependencies,
            usage=usage,
            confinement=ConfinementEvidence(
                backend_id=backend.backend_id,
                backend_version=backend.backend_version,
                profile_id=backend.profile_id,
                profile_version=backend.profile_version,
                verified_features=evidence.enforcement.verified_features,
            ),
            fixed_environment=FixedEnvironmentEvidence(
                node_controlled_path=True,
                ambient_pythonpath=False,
                ambient_user_site=False,
                ambient_package_manager_config=False,
                activation_script_sourced=non_actions.activation_script_sourced,
            ),
            started_at=started,
            completed_at=resources._now(),
            outcome=PreparationOutcome.PREPARED,
            reason_code=None,
            evidence_artifact_refs=evidence.evidence_artifact_refs,
        )
        data = manifest.model_dump_json().encode()
        if len(data) > 65536:
            raise DependencyError(
                "Final preparation evidence exceeds its bounded metadata allowance"
            )
        # Fixed metadata publication only. No new Resource, workspace or runtime operation.
        artifact = await self.artifacts.create_from_bytes(
            artifact_type="runtime.preparation.manifest",
            data=data,
            media_type="application/json",
            metadata={
                "binding_sha256": python_runtime_binding_digest(evidence.binding),
                "construction_sha256": digest_value(construction),
                "runtime_evidence_sha256": python_runtime_evidence_digest(evidence),
            },
        )
        if (
            self.runtime.repository.current(
                reservation.resource_ref,
                run_status=CapabilityRunStatus.RUNNING,
            )
            != current
        ):
            raise DependencyError("Current runtime changed during evidence publication")
        assert artifact.sha256 is not None and artifact.size_bytes is not None
        return RuntimePreparationReceipt(
            schema_version="runtime-preparation-receipt-v1",
            preparation_ref=permit.spec.preparation_ref,
            run_ref=permit.run_ref,
            resource_ref=reservation.resource_ref,
            manifest_ref=manifest.manifest_ref,
            manifest_artifact_ref=artifact.artifact_id,
            manifest_sha256=artifact.sha256,
            manifest_size_bytes=artifact.size_bytes,
            permit_ref=permit.permit_ref,
            permit_sha256=preparation_permit_digest(permit),
            node_id=permit.spec.node_id,
            provider_id=permit.spec.provider_id,
            provider_version=permit.spec.provider_version,
            outcome=PreparationOutcome.PREPARED,
            reason_code=None,
        )

    def _require_binding(self, request: RuntimePreparationInput) -> None:
        if request.permit != self._permit:
            raise DependencyError("Preparation service is bound to one exact admitted permit/Run")
