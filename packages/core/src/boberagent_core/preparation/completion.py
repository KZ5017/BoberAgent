"""E6 explicit terminal pump and Artifact-aware reconciliation, not an executor."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime

from boberagent_contracts import (
    ArtifactRef,
    CapabilityOutcomeCategory,
    CapabilityRunRef,
    CapabilityRunStatus,
    PreparationOutcome,
    PythonRuntimeEvidence,
    ResourceRef,
    RuntimePreparationManifest,
    RuntimePreparationReceipt,
    RuntimePreparationRef,
    preparation_permit_digest,
    python_runtime_binding_digest,
    python_runtime_evidence_digest,
)
from boberagent_transport import MaterializationEvidence
from boberagent_transport.preparation_runtime import RuntimePreparationOperation
from pydantic import ValidationError

from ..artifacts import CoreArtifactService
from ..clock import utc_now
from ..models import ArtifactContentState
from ..persistence import CoreDatabase
from ..results import ResultIngestionService
from ..results.models import ResultIngestionStatus
from .dispatch import CorePreparationDispatchService, PreparationDispatchError
from .models import PreparationAttempt, PreparationCompletionContext, PreparationLifecycle
from .runtime import CorePythonRuntimeService


class _AwaitingEvidence(Exception):
    pass


def _require(value: object, code: str) -> None:
    if not value:
        raise ValueError(code)


class CorePreparationCompletionService:
    """No dispatch from reconciliation; late Artifact availability is explicitly pumped."""

    def __init__(
        self,
        database: CoreDatabase,
        artifacts: CoreArtifactService,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._database, self._artifacts, self._clock = database, artifacts, clock

    def get(self, ref: RuntimePreparationRef) -> PreparationAttempt:
        with self._database.unit_of_work() as work:
            attempt = work.runtime_preparations.get(ref)
        if attempt is None:
            raise KeyError("unknown preparation")
        return attempt

    async def finalize(
        self,
        dispatch: CorePreparationDispatchService,
        ref: RuntimePreparationRef,
        *,
        materialization: MaterializationEvidence,
        resource_ref: ResourceRef,
        binding_sha256: str,
    ) -> PreparationAttempt:
        """Finish only a proven queued Run; never retry uncertain/failed execution."""
        attempt = self.get(ref)
        if (
            attempt.lifecycle.is_terminal
            or attempt.lifecycle is PreparationLifecycle.AWAITING_ARTIFACT
        ):
            return self.reconcile(ref)
        current = dispatch._current(ref)
        permit = current.permit
        assert permit is not None
        status = await dispatch._transport.query_run_status(permit.spec.node_id, permit.run_ref)
        if status is not CapabilityRunStatus.QUEUED:
            # Delivery may be uncertain; receive/reconcile existing outboxes, not resubmit.
            if attempt.completion_context is not None:
                return self.reconcile(ref)
            raise PreparationDispatchError("PREPARATION_DISPATCH_UNCERTAIN")
        # Address only an already existing Resource before any MATERIALIZE replay.
        # The supplied E4 projection is correlation, never the authoritative summary.
        runtime = await CorePythonRuntimeService(dispatch).exchange(
            ref,
            materialization=materialization,
            operation=RuntimePreparationOperation.RUNTIME_STATUS,
            resource_ref=resource_ref,
            binding_sha256=binding_sha256,
        )
        self._validate_context(
            PreparationCompletionContext(materialization=materialization, runtime=runtime)
        )
        source = await dispatch.materialize_source(ref)
        _require(source == materialization, "E4_CORRELATION_CONFLICT")
        self._validate_context(
            PreparationCompletionContext(materialization=source, runtime=runtime)
        )
        if attempt.completion_context is None:
            with self._database.unit_of_work() as work:
                attempt = work.runtime_preparations.bind_completion(
                    ref,
                    PreparationCompletionContext(materialization=source, runtime=runtime),
                    now=self._clock(),
                )
        else:
            old = attempt.completion_context
            _require(
                old.materialization == source
                and old.runtime.current == runtime.current
                and old.runtime.evidence == runtime.evidence
                and old.runtime.construction_sha256 == runtime.construction_sha256,
                "COMPLETION_CONTEXT_CHANGED",
            )
        provider = dispatch._router.select_provider(
            capability_id="runtime.prepare",
            operation="prepare",
            provider_id=permit.spec.provider_id,
            node_id=permit.spec.node_id,
        )
        delivery = dispatch._delivery(dispatch._current(ref))
        # Same envelope content/Run through the existing authenticated preparation path.
        await dispatch._router.dispatch(
            invocation=delivery.invocation, provider=provider, delivery=delivery
        )
        return self.get(ref)  # Result receipt/delivery remains separate from submission.

    def reconcile(self, ref: RuntimePreparationRef) -> PreparationAttempt:
        attempt = self.get(ref)
        if attempt.lifecycle.is_terminal:
            return attempt
        if attempt.reserved_run_ref is None:
            return attempt
        ingestion_service = ResultIngestionService(self._database, clock=self._clock)
        ingestion = ingestion_service.get_ingestion(attempt.reserved_run_ref)
        if ingestion is None:
            return attempt
        if not ingestion.status.is_complete:
            ingestion = ingestion_service.process_ingestion(attempt.reserved_run_ref)
        receipt = attempt.receipt
        try:
            _require(
                ingestion.status is ResultIngestionStatus.PROCESSED, "RESULT_INGESTION_REJECTED"
            )
            _require(ingestion.conflict_count == 0, "CONFLICTING_TERMINAL_RESULT")
            result = ingestion.result
            _require(
                ingestion.source_node_id == attempt.context.request.node_id, "RESULT_NODE_MISMATCH"
            )
            _require(
                result.execution_status is CapabilityRunStatus.COMPLETED
                and result.outcome.category is CapabilityOutcomeCategory.SUCCESS,
                "PREPARATION_RESULT_NOT_SUCCESSFUL",
            )
            _require(
                not (
                    result.observations
                    or result.findings
                    or result.effects
                    or result.sessions
                    or result.resources
                ),
                "PREPARATION_RESULT_UNEXPECTED_OBJECTS",
            )
            parsed = RuntimePreparationReceipt.model_validate(
                result.outcome.details.get("preparation_receipt")
            )
            _require(receipt is None or receipt == parsed, "RECEIPT_CONFLICT")
            receipt = parsed
            context = attempt.completion_context
            _require(context is not None, "AUTHORITATIVE_COMPLETION_CONTEXT_MISSING")
            assert context is not None
            self._validate_context(context)
            with self._database.unit_of_work() as work:
                permit = (
                    None
                    if attempt.permit_ref is None
                    else work.runtime_preparations.get_permit(attempt.permit_ref)
                )
            _require(permit is not None, "PERMIT_MISSING")
            assert permit is not None
            runtime, source = context.runtime, context.materialization
            _require(
                runtime.evidence is not None and runtime.current is not None, "E5_EVIDENCE_MISSING"
            )
            assert runtime.evidence and runtime.current
            _require(
                receipt.preparation_ref == ref
                and receipt.run_ref == permit.run_ref
                and receipt.permit_ref == permit.permit_ref
                and receipt.permit_sha256 == preparation_permit_digest(permit)
                and receipt.node_id == permit.spec.node_id
                and receipt.provider_id == permit.spec.provider_id
                and receipt.provider_version == permit.spec.provider_version
                and receipt.resource_ref == runtime.resource_ref
                and receipt.outcome is PreparationOutcome.PREPARED
                and runtime.evidence.binding.request.spec == permit.spec
                and source.preparation_ref == ref
                and source.run_ref == permit.run_ref,
                "RECEIPT_AUTHORITY_MISMATCH",
            )
            descriptors = [
                a for a in result.artifacts if a.artifact_id == receipt.manifest_artifact_ref
            ]
            _require(
                len(descriptors) == 1 and len(result.artifacts) == 1, "MANIFEST_DESCRIPTOR_MISSING"
            )
            descriptor = descriptors[0]
            _require(
                descriptor.sha256 == receipt.manifest_sha256
                and descriptor.size_bytes == receipt.manifest_size_bytes
                and descriptor.created_by_run == permit.run_ref
                and descriptor.artifact_type == "runtime.preparation.manifest",
                "MANIFEST_DESCRIPTOR_MISMATCH",
            )
            _require(
                descriptor.metadata
                == {
                    "binding_sha256": runtime.current.binding_sha256,
                    "construction_sha256": runtime.construction_sha256,
                    "runtime_evidence_sha256": python_runtime_evidence_digest(runtime.evidence),
                },
                "MANIFEST_BINDING_MISMATCH",
            )
            payload = self._content(receipt.manifest_artifact_ref, permit.run_ref)
            _require(
                len(payload) == receipt.manifest_size_bytes
                and hashlib.sha256(payload).hexdigest() == receipt.manifest_sha256,
                "MANIFEST_DIGEST_MISMATCH",
            )
            manifest = RuntimePreparationManifest.model_validate_json(payload)
            _require(
                manifest.manifest_ref == receipt.manifest_ref
                and manifest.spec == permit.spec
                and manifest.run_ref == permit.run_ref
                and manifest.permit_ref == permit.permit_ref
                and manifest.permit_sha256 == receipt.permit_sha256
                and manifest.resource_ref == runtime.resource_ref
                and manifest.outcome is PreparationOutcome.PREPARED,
                "MANIFEST_IDENTITY_MISMATCH",
            )
            # Independent authoritative summaries: never derive either count from the other.
            _require(
                manifest.materialization.file_count == source.file_count
                and manifest.materialization.total_bytes == source.materialized_bytes
                and manifest.materialization.tree_sha256 == source.tree_sha256
                and manifest.materialization.entrypoint_sha256
                == permit.spec.entrypoint.entry_sha256,
                "E4_MATERIALIZATION_SUMMARY_MISMATCH",
            )
            _require(
                manifest.usage == runtime.evidence.aggregate_usage, "E5_AGGREGATE_USAGE_MISMATCH"
            )
            _require(
                manifest.workspace_correlation == runtime.evidence.workspace_correlation
                and manifest.interpreter == runtime.evidence.binding.interpreter.summary
                and manifest.evidence_artifact_refs == runtime.evidence.evidence_artifact_refs,
                "E5_RUNTIME_SUMMARY_MISMATCH",
            )
            backend = runtime.evidence.binding.backend
            _require(
                manifest.confinement.backend_id == backend.backend_id
                and manifest.confinement.backend_version == backend.backend_version
                and manifest.confinement.profile_id == backend.profile_id
                and manifest.confinement.profile_version == backend.profile_version
                and set(manifest.confinement.verified_features)
                == set(permit.spec.profile.confinement.required_features),
                "CONFINEMENT_MISMATCH",
            )
            _require(
                permit.not_before
                <= manifest.started_at
                <= manifest.completed_at
                < permit.expires_at
                and runtime.evidence.completed_at <= manifest.completed_at,
                "COMPLETION_AUTHORITY_INTERVAL_MISMATCH",
            )
            for evidence_ref in manifest.evidence_artifact_refs:
                evidence = PythonRuntimeEvidence.model_validate_json(
                    self._content(evidence_ref, permit.run_ref)
                )
                _require(
                    evidence == runtime.evidence.model_copy(update={"evidence_artifact_refs": ()}),
                    "E5_ARTIFACT_EVIDENCE_MISMATCH",
                )
        except _AwaitingEvidence as error:
            return self._retain(
                attempt, PreparationLifecycle.AWAITING_ARTIFACT, receipt, error=str(error)
            )
        except (ValueError, TypeError, OSError, ValidationError):
            return self._retain(
                attempt, PreparationLifecycle.FAILED, receipt, error="PREPARATION_EVIDENCE_REJECTED"
            )
        return self._retain(attempt, PreparationLifecycle.COMPLETED, receipt, manifest=manifest)

    def _content(self, ref: ArtifactRef, run_ref: CapabilityRunRef) -> bytes:
        record = self._artifacts.get(ref)
        if record is None or record.content_state is not ArtifactContentState.AVAILABLE:
            raise _AwaitingEvidence(
                "ARTIFACT_SYNC_FAILED"
                if record and record.content_state is ArtifactContentState.FAILED
                else "ARTIFACT_SYNC_PENDING"
            )
        _require(record.descriptor.created_by_run == run_ref, "ARTIFACT_PRODUCER_MISMATCH")
        with self._artifacts.open_content(ref) as stream:
            payload = stream.read(65537)
        _require(
            len(payload) <= 65536
            and len(payload) == record.descriptor.size_bytes
            and hashlib.sha256(payload).hexdigest() == record.descriptor.sha256,
            "ARTIFACT_INTEGRITY_FAILURE",
        )
        return payload

    @staticmethod
    def _validate_context(context: PreparationCompletionContext) -> None:
        runtime, source = context.runtime, context.materialization
        current, evidence = runtime.current, runtime.evidence
        _require(
            current and evidence and runtime.construction_sha256, "CURRENT_E5_EVIDENCE_REQUIRED"
        )
        assert current and evidence
        binding = evidence.binding.request
        _require(
            current.validity.value == "VALID"
            and current.state.value == "READY"
            and current.phase.value == "PUBLISHED"
            and current.failure is None
            and evidence.verification == "VERIFIED"
            and evidence.failure is None
            and evidence.enforcement
            and evidence.enforcement.boot_generation == current.boot_generation
            and current.checked_at is not None
            and evidence.completed_at <= current.checked_at
            and evidence.environment
            and evidence.evidence_artifact_refs
            and current.binding_sha256 == python_runtime_binding_digest(evidence.binding),
            "CURRENT_E5_EVIDENCE_INVALID",
        )
        _require(
            source.preparation_ref == binding.spec.preparation_ref
            and source.permit_sha256 == binding.permit_sha256
            and source.budgets == binding.spec.budgets
            and source.materialization_id == binding.materialization_id
            and source.tree_sha256 == binding.source_tree_sha256
            and source.permit_ref == binding.permit_ref
            and source.run_ref == binding.run_ref
            and source.node_id == binding.spec.node_id
            and source.mission_ref == binding.spec.mission_ref
            and source.plan_ref == binding.spec.plan_ref
            and source.plan_intent_sha256 == binding.spec.plan_intent_sha256
            and source.raw_artifact_ref == binding.spec.source.plan_source.raw_artifact_ref
            and source.raw_sha256 == binding.spec.source.plan_source.raw_sha256
            and source.manifest_artifact_ref
            == binding.spec.source.plan_source.manifest_artifact_ref
            and source.manifest_sha256 == binding.spec.source.plan_source.manifest_sha256,
            "E4_E5_BINDING_CONFLICT",
        )
        _require(
            source.file_count <= evidence.aggregate_usage.file_count
            and source.materialized_bytes == evidence.aggregate_usage.materialized_bytes,
            "E4_E5_ACCOUNTING_CONFLICT",
        )

    def _retain(
        self,
        attempt: PreparationAttempt,
        lifecycle: PreparationLifecycle,
        receipt: RuntimePreparationReceipt | None,
        *,
        manifest: RuntimePreparationManifest | None = None,
        error: str | None = None,
    ) -> PreparationAttempt:
        with self._database.unit_of_work() as work:
            return work.runtime_preparations.retain_completion(
                attempt.preparation_ref,
                lifecycle=lifecycle,
                receipt=receipt,
                manifest=manifest,
                error_code=error,
                now=self._clock(),
            )
