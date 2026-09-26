"""Core-owned M20-B1 request, receipt, and Artifact-aware reconciliation.

No downloader, Node provider, network call, ZIP parser, or PoC inspection lives here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from boberagent_contracts import (
    CapabilityInvocation,
    CapabilityOutcomeCategory,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    PoCAcquisitionBounds,
    PoCAcquisitionRef,
    PoCSourceAcquisitionInput,
    PoCSourceAcquisitionReceipt,
)
from pydantic import ValidationError

from boberagent_core.artifacts import CoreArtifactService
from boberagent_core.clock import utc_now
from boberagent_core.persistence import CoreDatabase
from boberagent_core.research import (
    HitDecision,
    PoCCandidateRef,
    ResearchStatus,
    SourceClass,
    VulnerabilityHypothesisRef,
)
from boberagent_core.results.models import ResultIngestionStatus

from .models import PoCAcquisition, PoCAcquisitionStatus

CAPABILITY_ID = "poc.source_acquisition"
OPERATION = "acquire"
RECEIPT_KEY = "acquisition_receipt"


class PoCAcquisitionError(ValueError):
    """A selected source, ownership relationship, or lifecycle transition is invalid."""


class CorePoCAcquisitionService:
    """Persist one explicit attempt; reconcile without acquiring source or retrying a Run."""

    def __init__(
        self,
        database: CoreDatabase,
        artifacts: CoreArtifactService,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._database = database
        self._artifacts = artifacts
        self._clock = clock

    def create_acquisition(
        self,
        *,
        mission_ref: MissionRef,
        hypothesis_ref: VulnerabilityHypothesisRef,
        candidate_ref: PoCCandidateRef,
        selected_hit_id: int,
        bounds: PoCAcquisitionBounds,
    ) -> PoCAcquisition:
        """Bind one admitted historical hit; never select a newer hit implicitly."""

        if selected_hit_id < 1:
            raise PoCAcquisitionError("selected historical source hit is invalid")
        now = self._now()
        with self._database.unit_of_work() as work:
            mission = work.missions.get(mission_ref)
            hypothesis = work.research.get_hypothesis(hypothesis_ref)
            candidate = work.research.get_candidate(candidate_ref)
            hit = work.research.get_hit(selected_hit_id)
            if mission is None or hypothesis is None or candidate is None or hit is None:
                raise PoCAcquisitionError(
                    "selected Mission, hypothesis, candidate, or hit is missing"
                )
            attempt = work.research.get_attempt(hit.attempt_ref)
            if (
                hypothesis.mission_ref != mission_ref
                or candidate.mission_ref != mission_ref
                or candidate.hypothesis_ref != hypothesis_ref
                or hit.candidate_ref != candidate_ref
                or hit.decision is HitDecision.REJECTED
                or hit.source_identity != candidate.source_identity
                or attempt is None
                or attempt.hypothesis_ref != hypothesis_ref
                or attempt.request.mission_ref != mission_ref
                or attempt.provider_id != hit.provider_id
                or attempt.status not in {ResearchStatus.FOUND, ResearchStatus.PARTIAL}
            ):
                raise PoCAcquisitionError(
                    "selected historical hit does not belong to this Mission lead"
                )
            source = hit.source
            if (
                source.source_class is not SourceClass.REPOSITORY
                or candidate.source_class is not SourceClass.REPOSITORY
                or source.repository_identity is None
                or source.revision_claim is None
                or source.provider_result_id is None
            ):
                raise PoCAcquisitionError("selected hit is not a supported GitHub repository claim")
            try:
                repository_id = int(source.provider_result_id)
                typed_input = PoCSourceAcquisitionInput(
                    acquisition_ref=PoCAcquisitionRef(f"poc-acquisition-{uuid4().hex}"),
                    source_kind="github_repository",
                    repository_uri=source.repository_identity,
                    provider_repository_id=repository_id,
                    historical_ref=source.revision_claim,
                    bounds=bounds,
                )
            except (ValueError, ValidationError) as error:
                raise PoCAcquisitionError(
                    "selected hit is not a supported bounded GitHub repository claim"
                ) from error
            if source.source_uri != typed_input.repository_uri:
                raise PoCAcquisitionError("selected source URI and repository identity disagree")
            acquisition = PoCAcquisition(
                acquisition_ref=typed_input.acquisition_ref,
                mission_ref=mission_ref,
                hypothesis_ref=hypothesis_ref,
                candidate_ref=candidate_ref,
                selected_hit_id=selected_hit_id,
                research_attempt_ref=hit.attempt_ref,
                research_provider_id=hit.provider_id,
                source_identity=candidate.source_identity,
                source_uri=source.source_uri,
                repository_uri=typed_input.repository_uri,
                provider_repository_id=repository_id,
                historical_ref=typed_input.historical_ref,
                bounds=bounds,
                status=PoCAcquisitionStatus.REQUESTED,
                created_at=now,
                updated_at=now,
            )
            work.acquisitions.add(acquisition)
            return acquisition

    def get(self, acquisition_ref: PoCAcquisitionRef) -> PoCAcquisition | None:
        with self._database.unit_of_work() as work:
            return work.acquisitions.get(acquisition_ref)

    def list_for_candidate(self, candidate_ref: PoCCandidateRef) -> tuple[PoCAcquisition, ...]:
        with self._database.unit_of_work() as work:
            return work.acquisitions.list_for_candidate(candidate_ref)

    def build_invocation(
        self, acquisition_ref: PoCAcquisitionRef, run_ref: CapabilityRunRef
    ) -> CapabilityInvocation:
        """Build typed intent only. B1 has no live provider and does not submit transport."""

        acquisition = self._required(acquisition_ref)
        if (
            acquisition.status is not PoCAcquisitionStatus.REQUESTED
            and acquisition.run_ref != run_ref
        ):
            raise PoCAcquisitionError("acquisition is already bound to a different Run")
        return CapabilityInvocation(
            run_id=run_ref,
            capability_id=CAPABILITY_ID,
            operation=OPERATION,
            mission_ref=acquisition.mission_ref,
            inputs=PoCSourceAcquisitionInput(
                acquisition_ref=acquisition.acquisition_ref,
                source_kind="github_repository",
                repository_uri=acquisition.repository_uri,
                provider_repository_id=acquisition.provider_repository_id,
                historical_ref=acquisition.historical_ref,
                bounds=acquisition.bounds,
            ).model_dump(mode="json"),
        )

    def record_dispatched(
        self, acquisition_ref: PoCAcquisitionRef, run_ref: CapabilityRunRef
    ) -> PoCAcquisition:
        """Attach an already persisted normal Run and Router decision; never dispatch here."""

        with self._database.unit_of_work() as work:
            acquisition = work.acquisitions.get(acquisition_ref)
            if acquisition is None:
                raise PoCAcquisitionError("unknown PoCAcquisition")
            if (
                acquisition.status is PoCAcquisitionStatus.DISPATCHED
                and acquisition.run_ref == run_ref
            ):
                return acquisition
            if acquisition.status is not PoCAcquisitionStatus.REQUESTED:
                raise PoCAcquisitionError("acquisition cannot be dispatched from this state")
            run = work.runs.get(run_ref)
            decision = work.routing_decisions.get(run_ref)
            if (
                run is None
                or decision is None
                or run.mission_ref != acquisition.mission_ref
                or run.capability_id != CAPABILITY_ID
                or run.operation != OPERATION
                or decision.capability_id != CAPABILITY_ID
                or decision.operation != OPERATION
            ):
                raise PoCAcquisitionError("normal CapabilityRun and routing decision are required")
            return work.acquisitions.update(
                acquisition.model_copy(
                    update={
                        "status": PoCAcquisitionStatus.DISPATCHED,
                        "run_ref": run_ref,
                        "routing_provider_id": decision.provider_id,
                        "node_id": decision.node_id,
                        "updated_at": self._now(),
                    }
                )
            )

    def validate_receipt(
        self, acquisition: PoCAcquisition, receipt: PoCSourceAcquisitionReceipt
    ) -> None:
        """Check the typed Node claim against Core's immutable selection and routing."""

        if (
            receipt.acquisition_ref != acquisition.acquisition_ref
            or receipt.run_ref != acquisition.run_ref
            or receipt.source_kind != "github_repository"
            or receipt.repository_uri != acquisition.repository_uri
            or receipt.provider_repository_id != acquisition.provider_repository_id
            or receipt.historical_ref != acquisition.historical_ref
            or receipt.request_count > acquisition.bounds.max_outbound_requests
            or receipt.redirect_count > acquisition.bounds.max_redirects
            or receipt.raw_archive_size_bytes > acquisition.bounds.max_download_bytes
        ):
            raise PoCAcquisitionError(
                "acquisition receipt conflicts with selected source or bounds"
            )

    def reconcile(self, acquisition_ref: PoCAcquisitionRef) -> PoCAcquisition:
        """Replay from persisted Run/Result/Artifact state; never start another Run."""

        with self._database.unit_of_work() as work:
            acquisition = work.acquisitions.get(acquisition_ref)
            if acquisition is None:
                raise PoCAcquisitionError("unknown PoCAcquisition")
            if (
                acquisition.status.is_terminal
                or acquisition.status is PoCAcquisitionStatus.REQUESTED
            ):
                return acquisition
            assert acquisition.run_ref is not None
            ingestion = work.result_ingestions.get(acquisition.run_ref)
            run = work.runs.get(acquisition.run_ref)
        if run is None:
            return self._transition(
                acquisition, PoCAcquisitionStatus.INTERRUPTED, "CapabilityRun is missing"
            )
        if ingestion is None:
            if run.status.is_terminal:
                status = (
                    PoCAcquisitionStatus.FAILED
                    if run.status is CapabilityRunStatus.FAILED
                    else PoCAcquisitionStatus.INTERRUPTED
                )
                return self._transition(
                    acquisition, status, "terminal Run has no durable acquisition Result"
                )
            return acquisition
        if ingestion.status in {ResultIngestionStatus.REJECTED, ResultIngestionStatus.FAILED}:
            return self._transition(
                acquisition,
                PoCAcquisitionStatus.REJECTED,
                "canonical Result ingestion rejected acquisition output",
            )
        if ingestion.status is not ResultIngestionStatus.PROCESSED:
            return acquisition
        result = ingestion.result
        if ingestion.source_node_id is not None and ingestion.source_node_id != acquisition.node_id:
            return self._transition(
                acquisition, PoCAcquisitionStatus.REJECTED, "Result Node does not match routed Node"
            )
        if result.execution_status is not CapabilityRunStatus.COMPLETED:
            status = (
                PoCAcquisitionStatus.INTERRUPTED
                if result.execution_status
                in {CapabilityRunStatus.CANCELLED, CapabilityRunStatus.TIMED_OUT}
                else PoCAcquisitionStatus.FAILED
            )
            return self._transition(acquisition, status, "acquisition capability did not complete")
        if result.outcome.category is not CapabilityOutcomeCategory.SUCCESS:
            return self._transition(
                acquisition, PoCAcquisitionStatus.REJECTED, "acquisition receipt was not successful"
            )
        payload = result.outcome.details.get(RECEIPT_KEY)
        try:
            if not isinstance(payload, dict):
                raise ValueError("missing typed receipt")
            receipt = PoCSourceAcquisitionReceipt.model_validate(payload)
            self.validate_receipt(acquisition, receipt)
            if (
                result.observations
                or result.findings
                or result.effects
                or len(result.artifacts) != 2
                or receipt.raw_source not in result.artifacts
                or receipt.manifest not in result.artifacts
            ):
                raise ValueError(
                    "acquisition Result contains unexpected semantic output or Artifacts"
                )
        except (ValueError, ValidationError, TypeError):
            return self._transition(
                acquisition, PoCAcquisitionStatus.REJECTED, "acquisition receipt is invalid"
            )
        if acquisition.receipt is not None and acquisition.receipt != receipt:
            return self._transition(
                acquisition, PoCAcquisitionStatus.REJECTED, "persisted receipt changed"
            )
        if acquisition.status is PoCAcquisitionStatus.DISPATCHED:
            acquisition = self._transition(
                acquisition, PoCAcquisitionStatus.AWAITING_ARTIFACT, receipt=receipt
            )
        try:
            if not self._artifact_verified(receipt.raw_source) or not self._artifact_verified(
                receipt.manifest
            ):
                return acquisition
        except (PoCAcquisitionError, FileNotFoundError):
            return self._transition(
                acquisition,
                PoCAcquisitionStatus.REJECTED,
                "verified Artifact conflicts with receipt",
            )
        return self._transition(acquisition, PoCAcquisitionStatus.COMPLETED)

    def reject(self, acquisition_ref: PoCAcquisitionRef, diagnostic: str) -> PoCAcquisition:
        """Record a safe policy rejection without adding a new execution path."""

        if not diagnostic or len(diagnostic) > 512:
            raise PoCAcquisitionError("rejection diagnostic must be bounded")
        return self._transition(
            self._required(acquisition_ref), PoCAcquisitionStatus.REJECTED, diagnostic
        )

    def fail(self, acquisition_ref: PoCAcquisitionRef, diagnostic: str) -> PoCAcquisition:
        """Record a bounded operational failure without retrying acquisition."""

        if not diagnostic or len(diagnostic) > 512:
            raise PoCAcquisitionError("failure diagnostic must be bounded")
        return self._transition(
            self._required(acquisition_ref), PoCAcquisitionStatus.FAILED, diagnostic
        )

    def interrupt(self, acquisition_ref: PoCAcquisitionRef, diagnostic: str) -> PoCAcquisition:
        """Record an unprovable interrupted attempt without creating a new Run."""

        if not diagnostic or len(diagnostic) > 512:
            raise PoCAcquisitionError("interruption diagnostic must be bounded")
        return self._transition(
            self._required(acquisition_ref), PoCAcquisitionStatus.INTERRUPTED, diagnostic
        )

    def _artifact_verified(self, descriptor: object) -> bool:
        from boberagent_contracts import ArtifactDescriptor

        assert isinstance(descriptor, ArtifactDescriptor)
        record = self._artifacts.get(descriptor.artifact_id)
        if record is None or not record.content_available:
            return False
        if record.descriptor != descriptor or not self._artifacts.content_available(
            descriptor.artifact_id
        ):
            raise PoCAcquisitionError(
                "available Artifact metadata conflicts with acquisition receipt"
            )
        digest = hashlib.sha256()
        size = 0
        with self._artifacts.open_content(descriptor.artifact_id) as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        if digest.hexdigest() != descriptor.sha256 or size != descriptor.size_bytes:
            raise PoCAcquisitionError(
                "available Artifact content conflicts with acquisition receipt"
            )
        return True

    def _transition(
        self,
        acquisition: PoCAcquisition,
        status: PoCAcquisitionStatus,
        diagnostic: str | None = None,
        *,
        receipt: PoCSourceAcquisitionReceipt | None = None,
    ) -> PoCAcquisition:
        with self._database.unit_of_work() as work:
            current = work.acquisitions.get(acquisition.acquisition_ref)
            if current is None:
                raise PoCAcquisitionError("unknown PoCAcquisition")
            if current.status is status and current.receipt == (receipt or current.receipt):
                return current
            return work.acquisitions.update(
                current.model_copy(
                    update={
                        "status": status,
                        "receipt": receipt or current.receipt,
                        "updated_at": self._now(),
                        "diagnostic": diagnostic,
                    }
                )
            )

    def _required(self, acquisition_ref: PoCAcquisitionRef) -> PoCAcquisition:
        with self._database.unit_of_work() as work:
            acquisition = work.acquisitions.get(acquisition_ref)
        if acquisition is None:
            raise PoCAcquisitionError("unknown PoCAcquisition")
        return acquisition

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise PoCAcquisitionError("acquisition clock must return timezone-aware UTC")
        return value
