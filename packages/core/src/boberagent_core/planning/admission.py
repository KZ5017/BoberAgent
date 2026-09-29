"""Metadata-only authoritative admission. No construction, policy or execution."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_contracts.plan_requirements import PlanSource
from pydantic import ValidationError

from boberagent_core.acquisitions.models import PoCAcquisition, PoCAcquisitionStatus
from boberagent_core.clock import utc_now
from boberagent_core.inspections.classification_models import (
    ClassificationInspectionLimits,
    SupportClassification,
    SupportClassificationDocument,
    semantic_digest,
)
from boberagent_core.inspections.config_identity import (
    classification_config_fingerprint,
    evidence_config_fingerprint,
)
from boberagent_core.inspections.models import InspectionStatus, PoCInspection
from boberagent_core.inspections.semantic_models import (
    SemanticInspectionDocument,
    SemanticInspectionLimits,
)
from boberagent_core.persistence import CoreDatabase
from boberagent_core.persistence.repositories import CoreUnitOfWork

from .admission_errors import AdmissionErrorCode, PlanningAdmissionError
from .admission_models import (
    PlanningAdmissionOutcome,
    PlanningAdmissionRequest,
    PlanningAdmissionResult,
)
from .models import (
    PlanningAttempt,
    PlanningAttemptLifecycle,
    PlanningAttemptRef,
    PlanningDisposition,
    PlanningInspectionProvenance,
    PlanningRequest,
)


def _require(condition: bool, code: AdmissionErrorCode) -> None:
    if not condition:
        raise PlanningAdmissionError(code)


class CorePlanningAdmissionService:
    """Explicit immediate pump. Invalid evidence fails before creating an attempt.

    Unsupported completion and attempt insertion share one Core UoW. An internal failure
    rolls back the whole admission, never leaving a guessed completed determination.
    Eligible attempts remain REQUESTED for D4/D6; eligibility is not plan validity.
    """

    def __init__(self, database: CoreDatabase, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._database = database
        self._clock = clock

    def admit(self, request: PlanningAdmissionRequest) -> PlanningAdmissionResult:
        # Frozen Pydantic bypass APIs are not trusted at an application boundary.
        try:
            if not isinstance(request, PlanningAdmissionRequest) or (
                set(request.__dict__) - set(PlanningAdmissionRequest.model_fields)
            ):
                raise ValueError("invalid admission shape")
            request = PlanningAdmissionRequest.model_validate_json(request.model_dump_json())
        except (ValueError, TypeError, AttributeError):
            raise PlanningAdmissionError(AdmissionErrorCode.REQUEST_INVALID) from None
        try:
            with self._database.unit_of_work() as work:
                canonical = _authoritative_request(work, request)
                now = self._clock()
                _require(
                    now.tzinfo is not None and now.utcoffset() == timedelta(0),
                    AdmissionErrorCode.INTERNAL_ERROR,
                )
                unsupported = (
                    canonical.inspection.classification.classification
                    is SupportClassification.UNSUPPORTED
                )
                proposed_ref = PlanningAttemptRef(f"planning-attempt-{uuid4().hex}")
                attempt = work.planning_attempts.add(
                    PlanningAttempt(
                        planning_attempt_ref=proposed_ref,
                        request=canonical,
                        lifecycle=PlanningAttemptLifecycle.REQUESTED,
                        disposition=PlanningDisposition.UNSUPPORTED if unsupported else None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                # Existing active/terminal history is returned, not advanced or retried.
                if attempt.planning_attempt_ref == proposed_ref and unsupported:
                    attempt = work.planning_attempts.update_lifecycle(
                        proposed_ref,
                        PlanningAttemptLifecycle.EVALUATING,
                        expected_state=PlanningAttemptLifecycle.REQUESTED,
                        expected_revision=0,
                        updated_at=now,
                        disposition=PlanningDisposition.UNSUPPORTED,
                    )
                    attempt = work.planning_attempts.update_lifecycle(
                        proposed_ref,
                        PlanningAttemptLifecycle.COMPLETED,
                        expected_state=PlanningAttemptLifecycle.EVALUATING,
                        expected_revision=0,
                        updated_at=now,
                        disposition=PlanningDisposition.UNSUPPORTED,
                    )
                return _result(attempt)
        except PlanningAdmissionError:
            raise
        except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
            raise PlanningAdmissionError(AdmissionErrorCode.RECORD_INVALID) from None
        except Exception:
            raise PlanningAdmissionError(AdmissionErrorCode.INTERNAL_ERROR) from None

    def get_admission(self, attempt_ref: PlanningAttemptRef) -> PlanningAdmissionResult | None:
        """Inspect persisted admission history; does not reclassify or resume planning."""
        with self._database.unit_of_work() as work:
            attempt = work.planning_attempts.get(attempt_ref)
            return None if attempt is None else _result(attempt)


def _result(attempt: PlanningAttempt) -> PlanningAdmissionResult:
    outcome = {
        SupportClassification.AUTOMATIC: PlanningAdmissionOutcome.ELIGIBLE_AUTOMATIC,
        SupportClassification.ASSISTED: PlanningAdmissionOutcome.ELIGIBLE_ASSISTED,
        SupportClassification.UNSUPPORTED: PlanningAdmissionOutcome.REJECTED_UNSUPPORTED,
    }[attempt.request.inspection.classification.classification]
    return PlanningAdmissionResult(outcome=outcome, attempt=attempt)


def _authoritative_request(
    work: CoreUnitOfWork, request: PlanningAdmissionRequest
) -> PlanningRequest:
    mission = work.missions.get(request.mission_ref)
    acquisition = work.acquisitions.get(request.acquisition_ref)
    c2 = work.inspections.get(request.semantic_inspection_ref)
    c3 = work.inspections.get(request.classification_inspection_ref)
    if mission is None or acquisition is None or c2 is None or c3 is None:
        raise PlanningAdmissionError(AdmissionErrorCode.UPSTREAM_NOT_FOUND)
    # Revalidate snapshots, including discriminated document types, at this trust boundary.
    acquisition = PoCAcquisition.model_validate_json(acquisition.model_dump_json())
    c2 = PoCInspection.model_validate_json(c2.model_dump_json())
    c3 = PoCInspection.model_validate_json(c3.model_dump_json())
    _require(
        acquisition.mission_ref == mission.mission_ref
        and c2.mission_ref == mission.mission_ref
        and c3.mission_ref == mission.mission_ref,
        AdmissionErrorCode.OWNERSHIP_MISMATCH,
    )
    _require(
        acquisition.status is PoCAcquisitionStatus.COMPLETED,
        AdmissionErrorCode.ACQUISITION_NOT_COMPLETED,
    )
    _require(c2.status is InspectionStatus.COMPLETED, AdmissionErrorCode.C2_NOT_COMPLETED)
    _require(c3.status is InspectionStatus.COMPLETED, AdmissionErrorCode.C3_NOT_COMPLETED)
    _require(
        (c2.profile_id, c2.profile_version) == ("m20-c2-deterministic", "2")
        and (c3.profile_id, c3.profile_version) == ("m20-c3-support-classifier", "2"),
        AdmissionErrorCode.PROFILE_UNSUPPORTED,
    )
    hypothesis = work.research.get_hypothesis(acquisition.hypothesis_ref)
    candidate = work.research.get_candidate(acquisition.candidate_ref)
    if hypothesis is None or candidate is None:
        raise PlanningAdmissionError(AdmissionErrorCode.UPSTREAM_NOT_FOUND)
    asset = work.assets.get(hypothesis.asset_ref)
    service = None if hypothesis.service_ref is None else work.services.get(hypothesis.service_ref)
    _require(
        hypothesis.mission_ref == mission.mission_ref
        and candidate.mission_ref == mission.mission_ref
        and candidate.hypothesis_ref == hypothesis.hypothesis_ref
        and asset is not None
        and asset.mission_ref == mission.mission_ref
        and (
            hypothesis.service_ref is None
            or (service is not None and service.asset_ref == asset.asset_ref)
        ),
        AdmissionErrorCode.OWNERSHIP_MISMATCH,
    )
    _require(
        candidate.source_identity == acquisition.source_identity,
        AdmissionErrorCode.SOURCE_MISMATCH,
    )
    receipt = acquisition.receipt
    if receipt is None:
        raise PlanningAdmissionError(AdmissionErrorCode.SOURCE_MISMATCH)
    _require(
        receipt.repository_uri == acquisition.repository_uri
        and receipt.provider_repository_id == acquisition.provider_repository_id
        and receipt.historical_ref == acquisition.historical_ref
        and receipt.source_kind == acquisition.source_kind
        and receipt.fixture_port == acquisition.fixture_port,
        AdmissionErrorCode.SOURCE_MISMATCH,
    )
    run = work.runs.get(receipt.run_ref)
    _require(
        run is not None and run.mission_ref == mission.mission_ref,
        AdmissionErrorCode.OWNERSHIP_MISMATCH,
    )
    raw = work.artifacts.get_record(receipt.raw_source.artifact_id)
    manifest = work.artifacts.get_record(receipt.manifest.artifact_id)
    _require(
        raw is not None
        and manifest is not None
        and raw.content_available
        and manifest.content_available
        and raw.descriptor == receipt.raw_source
        and manifest.descriptor == receipt.manifest,
        AdmissionErrorCode.ARTIFACT_MISMATCH,
    )
    source = PlanSource(
        acquisition_ref=acquisition.acquisition_ref,
        raw_artifact_ref=receipt.raw_source.artifact_id,
        raw_sha256=receipt.raw_archive_sha256,
        raw_size_bytes=receipt.raw_archive_size_bytes,
        manifest_artifact_ref=receipt.manifest.artifact_id,
        manifest_sha256=receipt.manifest_sha256,
        resolved_commit=receipt.resolved_commit_sha,
    )
    for inspection in (c2, c3):
        _require(
            inspection.acquisition_ref == acquisition.acquisition_ref
            and inspection.hypothesis_ref == hypothesis.hypothesis_ref
            and inspection.candidate_ref == candidate.candidate_ref
            and inspection.raw_artifact_ref == source.raw_artifact_ref
            and inspection.raw_sha256 == source.raw_sha256
            and inspection.raw_size_bytes == source.raw_size_bytes
            and inspection.manifest_artifact_ref == source.manifest_artifact_ref
            and inspection.manifest_sha256 == source.manifest_sha256
            and inspection.resolved_commit_sha == source.resolved_commit,
            AdmissionErrorCode.SOURCE_MISMATCH,
        )
    semantic = c2.document
    classification = c3.document
    limits = c3.limits
    if (
        not isinstance(semantic, SemanticInspectionDocument)
        or not isinstance(classification, SupportClassificationDocument)
        or not isinstance(c2.limits, SemanticInspectionLimits)
        or not isinstance(limits, ClassificationInspectionLimits)
    ):
        raise PlanningAdmissionError(AdmissionErrorCode.RECORD_INVALID)
    _require(
        c2.config_fingerprint == evidence_config_fingerprint(c2.limits, c2.selected_paths)
        and c3.config_fingerprint == classification_config_fingerprint(limits)
        and not c3.selected_paths
        and c2.selected_paths == tuple(sorted(set(c2.selected_paths))),
        AdmissionErrorCode.CONFIGURATION_MISMATCH,
    )
    parent_digest = semantic_digest(semantic)
    _require(
        classification.semantic_inspection_ref == c2.inspection_ref
        and limits.semantic_inspection_ref == c2.inspection_ref
        and classification.semantic_document_sha256 == parent_digest
        and limits.semantic_document_sha256 == parent_digest,
        AdmissionErrorCode.C3_PARENT_MISMATCH,
    )
    _reference_integrity(semantic, classification, limits)
    return PlanningRequest(
        profile=request.planner_profile,
        profile_version=request.planner_version,
        policy_profile=request.policy_profile,
        policy_version=request.policy_version,
        mission_ref=mission.mission_ref,
        hypothesis_ref=hypothesis.hypothesis_ref,
        candidate_ref=candidate.candidate_ref,
        source=source,
        inspection=PlanningInspectionProvenance(
            classification_ref=c3.inspection_ref,
            classification_sha256=canonical_digest(classification),
            classification=classification,
        ),
    )


def _reference_integrity(
    semantic: SemanticInspectionDocument,
    classification: SupportClassificationDocument,
    limits: ClassificationInspectionLimits,
) -> None:
    """Check bounded metadata references only; neither classify nor inspect source again."""
    items = {
        item.item_id
        for collection in (
            semantic.facts,
            semantic.entrypoint_candidates,
            semantic.parameter_candidates,
            semantic.dependency_observations,
            semantic.requirements,
            semantic.behavior_indicators,
            semantic.risk_indicators,
            semantic.unknowns,
        )
        for item in collection
    }
    unknowns = {item.item_id for item in semantic.unknowns}
    conflicts = {item.conflict_id for item in semantic.conflicts}
    paths = {entry.path for entry in semantic.coverage}
    _require(
        len(items) + len(conflicts) <= limits.classifier_config.max_input_items
        and len(paths) <= limits.classifier_config.max_coverage_paths
        and all(
            set(reason.item_refs) <= items
            and set(reason.conflict_refs) <= conflicts
            and set(reason.coverage_paths) <= paths
            for reason in classification.reasons
        )
        and set(classification.coverage.material_paths)
        | set(classification.coverage.irrelevant_paths)
        == paths
        and set(classification.blocking_unknown_refs) <= unknowns
        and set(classification.assistance_unknown_refs) <= unknowns
        and set(classification.blocking_conflict_refs) <= conflicts,
        AdmissionErrorCode.RECORD_INVALID,
    )
