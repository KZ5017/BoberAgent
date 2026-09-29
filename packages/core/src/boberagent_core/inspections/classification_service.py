"""Durable C3 attempts consuming only completed, validated C2 inspection history."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

from pydantic import ValidationError

from boberagent_core.clock import utc_now
from boberagent_core.persistence import CoreDatabase

from .classification_models import (
    CLASSIFIER_PROFILE_ID,
    CLASSIFIER_PROFILE_VERSION,
    ClassificationInspectionLimits,
    ClassifierConfiguration,
    SupportClassificationDocument,
    semantic_digest,
)
from .classifier import classify_support, validate_classification_evidence
from .config_identity import classification_config_fingerprint
from .errors import InspectionError
from .identity import PoCInspectionRef
from .models import InspectionStatus, PoCInspection
from .semantic_models import SemanticInspectionDocument


def _semantic(value: PoCInspection | None) -> tuple[PoCInspection, SemanticInspectionDocument]:
    if value is None:
        raise InspectionError("CLASSIFICATION_INPUT_NOT_COMPLETED_C2")
    try:
        value = PoCInspection.model_validate_json(value.model_dump_json())
    except ValidationError:
        raise InspectionError("CLASSIFICATION_INPUT_INVALID") from None
    if value.status is not InspectionStatus.COMPLETED or not isinstance(
        value.document, SemanticInspectionDocument
    ):
        raise InspectionError("CLASSIFICATION_INPUT_NOT_COMPLETED_C2")
    if value.profile_version != "2":
        raise InspectionError("CLASSIFICATION_INPUT_PROFILE_UNSUPPORTED")
    return value, value.document


class CorePoCSupportClassificationService:
    """Explicit create/classify pump. Never opens Artifacts or calls the C2 extractor."""

    def __init__(self, database: CoreDatabase, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._database = database
        self._clock = clock

    def create(
        self,
        semantic_inspection_ref: PoCInspectionRef,
        *,
        config: ClassifierConfiguration | None = None,
        force_new: bool = False,
    ) -> PoCInspection:
        config = ClassifierConfiguration.model_validate_json(
            (config or ClassifierConfiguration()).model_dump_json()
        )
        with self._database.unit_of_work() as work:
            source, document = _semantic(work.inspections.get(semantic_inspection_ref))
            limits = ClassificationInspectionLimits(
                semantic_inspection_ref=source.inspection_ref,
                semantic_document_sha256=semantic_digest(document),
                classifier_config=config,
            )
            fingerprint = classification_config_fingerprint(limits)
            if not force_new:
                for previous in work.inspections.list_for_acquisition(source.acquisition_ref):
                    if (
                        previous.profile_id == CLASSIFIER_PROFILE_ID
                        and previous.profile_version == CLASSIFIER_PROFILE_VERSION
                        and previous.config_fingerprint == fingerprint
                        and previous.raw_sha256 == source.raw_sha256
                        and previous.manifest_sha256 == source.manifest_sha256
                        and previous.status
                        in {InspectionStatus.REQUESTED, InspectionStatus.COMPLETED}
                    ):
                        return previous
            result = PoCInspection(
                **source.model_dump(
                    exclude={
                        "inspection_ref",
                        "profile_id",
                        "profile_version",
                        "config_fingerprint",
                        "limits",
                        "selected_paths",
                        "status",
                        "created_at",
                        "started_at",
                        "finished_at",
                        "document",
                        "diagnostic",
                    }
                ),
                inspection_ref=PoCInspectionRef(f"poc-inspection-{uuid4().hex}"),
                profile_id=CLASSIFIER_PROFILE_ID,
                profile_version=CLASSIFIER_PROFILE_VERSION,
                config_fingerprint=fingerprint,
                limits=limits,
                status=InspectionStatus.REQUESTED,
                created_at=self._now(),
            )
            work.inspections.add(result)
            return result

    def get(self, inspection_ref: PoCInspectionRef) -> PoCInspection | None:
        with self._database.unit_of_work() as work:
            return work.inspections.get(inspection_ref)

    def classify(self, inspection_ref: PoCInspectionRef) -> PoCInspection:
        with self._database.unit_of_work() as work:
            current = work.inspections.get(inspection_ref)
            if current is None:
                raise InspectionError("INSPECTION_NOT_FOUND")
            if current.profile_id != CLASSIFIER_PROFILE_ID:
                raise InspectionError("CLASSIFICATION_PROFILE_INVALID")
            if current.status is InspectionStatus.COMPLETED:
                return current
            if current.profile_version != CLASSIFIER_PROFILE_VERSION:
                raise InspectionError("CLASSIFICATION_PROFILE_INVALID")
            if current.status is not InspectionStatus.REQUESTED:
                raise InspectionError("INSPECTION_NOT_REQUESTED")
            current = work.inspections.update(
                current.model_copy(
                    update={
                        "status": InspectionStatus.INSPECTING,
                        "started_at": self._now(),
                    }
                )
            )
        try:
            limits = current.limits
            if not isinstance(limits, ClassificationInspectionLimits):
                raise InspectionError("CLASSIFICATION_INPUT_INVALID")
            with self._database.unit_of_work() as work:
                source, document = _semantic(work.inspections.get(limits.semantic_inspection_ref))
            # The new attempt must bind the same source/ownership as its C2 parent.
            keys = (
                "mission_ref",
                "hypothesis_ref",
                "candidate_ref",
                "acquisition_ref",
                "raw_artifact_ref",
                "raw_sha256",
                "raw_size_bytes",
                "manifest_artifact_ref",
                "manifest_sha256",
                "resolved_commit_sha",
            )
            if any(getattr(current, key) != getattr(source, key) for key in keys) or (
                limits.semantic_document_sha256 != semantic_digest(document)
            ):
                raise InspectionError("CLASSIFICATION_INPUT_CHANGED")
            result = classify_support(source.inspection_ref, document, limits.classifier_config)
            result = SupportClassificationDocument.model_validate_json(result.model_dump_json())
            validate_classification_evidence(result, document)
            return self._finish(current, InspectionStatus.COMPLETED, document=result)
        except InspectionError as error:
            return self._finish(current, InspectionStatus.FAILED, diagnostic=error.code)
        except Exception:
            self._finish(current, InspectionStatus.FAILED, diagnostic="CLASSIFIER_INTERNAL_ERROR")
            raise InspectionError("CLASSIFIER_INTERNAL_ERROR") from None

    def recover_interrupted(self) -> tuple[PoCInspection, ...]:
        """No guessed classification or automatic rerun after an unproven crash."""
        with self._database.unit_of_work() as work:
            return tuple(
                work.inspections.update(
                    item.model_copy(
                        update={
                            "status": InspectionStatus.INTERRUPTED,
                            "finished_at": self._now(),
                            "diagnostic": "INSPECTION_INTERRUPTED",
                        }
                    )
                )
                for item in work.inspections.list_inspecting()
                if item.profile_id == CLASSIFIER_PROFILE_ID
            )

    def _finish(
        self,
        current: PoCInspection,
        status: InspectionStatus,
        *,
        document: SupportClassificationDocument | None = None,
        diagnostic: str | None = None,
    ) -> PoCInspection:
        with self._database.unit_of_work() as work:
            stored = work.inspections.get(current.inspection_ref)
            if stored is None or stored.status is not InspectionStatus.INSPECTING:
                raise InspectionError("INSPECTION_STATE_CONFLICT")
            # model_copy is intentionally followed by full validation on this boundary.
            updated = stored.model_copy(
                update={
                    "status": status,
                    "finished_at": self._now(),
                    "document": document,
                    "diagnostic": diagnostic,
                }
            )
            return work.inspections.update(
                PoCInspection.model_validate_json(updated.model_dump_json())
            )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise InspectionError("INSPECTION_CLOCK_INVALID")
        return value
