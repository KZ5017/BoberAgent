"""Core-owned research persistence; all methods share the caller's transaction."""

from __future__ import annotations

from datetime import datetime

from boberagent_contracts import AssetRef, MissionRef, ObservationRef, ServiceRef
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from boberagent_core.persistence.orm import (
    PoCCandidateRow,
    ResearchAttemptRow,
    ResearchSourceHitRow,
    VulnerabilityHypothesisRow,
)

from .models import (
    HitDecision,
    HypothesisStatus,
    PoCCandidate,
    PoCCandidateRef,
    ResearchAttempt,
    ResearchAttemptRef,
    ResearchRequest,
    ResearchSourceHit,
    ResearchStatus,
    SourceClass,
    SourceHit,
    VulnerabilityHypothesis,
    VulnerabilityHypothesisRef,
)


class ResearchRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_hypothesis(self, hypothesis: VulnerabilityHypothesis) -> None:
        self._session.add(
            VulnerabilityHypothesisRow(
                hypothesis_id=str(hypothesis.hypothesis_ref),
                mission_id=str(hypothesis.mission_ref),
                asset_id=str(hypothesis.asset_ref),
                service_id=None if hypothesis.service_ref is None else str(hypothesis.service_ref),
                claim=hypothesis.claim,
                vulnerability_ids_json=list(hypothesis.vulnerability_ids),
                product=hypothesis.product,
                version=hypothesis.version,
                observation_refs_json=[str(ref) for ref in hypothesis.supporting_observation_refs],
                provenance=hypothesis.provenance,
                status=hypothesis.status.value,
                created_at=hypothesis.created_at,
            )
        )
        self._session.flush()

    def get_hypothesis(
        self, hypothesis_ref: VulnerabilityHypothesisRef
    ) -> VulnerabilityHypothesis | None:
        row = self._session.get(VulnerabilityHypothesisRow, str(hypothesis_ref))
        return None if row is None else _hypothesis(row)

    def list_hypotheses(self, mission_ref: str) -> tuple[VulnerabilityHypothesis, ...]:
        rows = self._session.scalars(
            select(VulnerabilityHypothesisRow)
            .where(VulnerabilityHypothesisRow.mission_id == mission_ref)
            .order_by(
                VulnerabilityHypothesisRow.created_at, VulnerabilityHypothesisRow.hypothesis_id
            )
        )
        return tuple(_hypothesis(row) for row in rows)

    def retire_hypothesis(self, hypothesis_ref: VulnerabilityHypothesisRef) -> None:
        row = self._session.get(VulnerabilityHypothesisRow, str(hypothesis_ref))
        if row is None:
            raise KeyError("unknown VulnerabilityHypothesis")
        row.status = HypothesisStatus.RETIRED.value
        self._session.flush()

    def add_attempt(self, attempt: ResearchAttempt) -> None:
        self._session.add(
            ResearchAttemptRow(
                attempt_id=str(attempt.attempt_ref),
                hypothesis_id=str(attempt.hypothesis_ref),
                provider_id=attempt.provider_id,
                request_json=attempt.request.model_dump(mode="json"),
                status=attempt.status.value,
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
                diagnostic=attempt.diagnostic,
            )
        )
        self._session.flush()

    def finish_attempt(self, attempt: ResearchAttempt) -> None:
        row = self._session.get(ResearchAttemptRow, str(attempt.attempt_ref))
        if row is None or row.status != ResearchStatus.STARTED.value:
            raise ValueError("research attempt is not pending")
        row.status = attempt.status.value
        row.finished_at = attempt.finished_at
        row.diagnostic = attempt.diagnostic
        self._session.flush()

    def interrupt_stale_attempts(self, *, cutoff: datetime, finished_at: datetime) -> int:
        """Terminalize only rows still STARTED at or before the safe cutoff."""

        result = self._session.connection().execute(
            update(ResearchAttemptRow)
            .where(
                ResearchAttemptRow.status == ResearchStatus.STARTED.value,
                ResearchAttemptRow.started_at <= cutoff,
            )
            .values(
                status=ResearchStatus.INTERRUPTED.value,
                finished_at=finished_at,
                diagnostic="Core research attempt interrupted before a result was recorded",
            )
        )
        return result.rowcount

    def get_attempt(self, attempt_ref: ResearchAttemptRef) -> ResearchAttempt | None:
        row = self._session.get(ResearchAttemptRow, str(attempt_ref))
        return None if row is None else _attempt(row)

    def list_attempts(
        self, hypothesis_ref: VulnerabilityHypothesisRef
    ) -> tuple[ResearchAttempt, ...]:
        rows = self._session.scalars(
            select(ResearchAttemptRow)
            .where(ResearchAttemptRow.hypothesis_id == str(hypothesis_ref))
            .order_by(ResearchAttemptRow.started_at, ResearchAttemptRow.attempt_id)
        )
        return tuple(_attempt(row) for row in rows)

    def add_candidate(self, candidate: PoCCandidate) -> None:
        self._session.add(
            PoCCandidateRow(
                candidate_id=str(candidate.candidate_ref),
                mission_id=str(candidate.mission_ref),
                hypothesis_id=str(candidate.hypothesis_ref),
                source_identity=candidate.source_identity,
                source_class=candidate.source_class.value,
                source_uri=candidate.source_uri,
                first_seen_at=candidate.first_seen_at,
                last_seen_at=candidate.last_seen_at,
            )
        )
        self._session.flush()

    def candidate_by_source(
        self, hypothesis_ref: VulnerabilityHypothesisRef, source_identity: str
    ) -> PoCCandidate | None:
        row = self._session.scalar(
            select(PoCCandidateRow).where(
                PoCCandidateRow.hypothesis_id == str(hypothesis_ref),
                PoCCandidateRow.source_identity == source_identity,
            )
        )
        return None if row is None else _candidate(row)

    def touch_candidate(self, candidate_ref: PoCCandidateRef, observed_at: datetime) -> None:
        row = self._session.get(PoCCandidateRow, str(candidate_ref))
        if row is None:
            raise KeyError("unknown PoCCandidate")
        if observed_at > row.last_seen_at:
            row.last_seen_at = observed_at
        self._session.flush()

    def get_candidate(self, candidate_ref: PoCCandidateRef) -> PoCCandidate | None:
        row = self._session.get(PoCCandidateRow, str(candidate_ref))
        return None if row is None else _candidate(row)

    def list_candidates(
        self, hypothesis_ref: VulnerabilityHypothesisRef
    ) -> tuple[PoCCandidate, ...]:
        rows = self._session.scalars(
            select(PoCCandidateRow)
            .where(PoCCandidateRow.hypothesis_id == str(hypothesis_ref))
            .order_by(PoCCandidateRow.first_seen_at, PoCCandidateRow.candidate_id)
        )
        return tuple(_candidate(row) for row in rows)

    def add_hit(self, hit: ResearchSourceHit) -> ResearchSourceHit:
        row = ResearchSourceHitRow(
            attempt_id=str(hit.attempt_ref),
            candidate_id=None if hit.candidate_ref is None else str(hit.candidate_ref),
            provider_id=hit.provider_id,
            source_json=hit.source.model_dump(mode="json"),
            source_identity=hit.source_identity,
            decision=hit.decision.value,
            decision_reason=hit.decision_reason,
            observed_at=hit.observed_at,
        )
        self._session.add(row)
        self._session.flush()
        return _hit(row)

    def list_hits(self, attempt_ref: ResearchAttemptRef) -> tuple[ResearchSourceHit, ...]:
        rows = self._session.scalars(
            select(ResearchSourceHitRow)
            .where(ResearchSourceHitRow.attempt_id == str(attempt_ref))
            .order_by(ResearchSourceHitRow.hit_id)
        )
        return tuple(_hit(row) for row in rows)


def _hypothesis(row: VulnerabilityHypothesisRow) -> VulnerabilityHypothesis:
    return VulnerabilityHypothesis(
        hypothesis_ref=VulnerabilityHypothesisRef(row.hypothesis_id),
        mission_ref=MissionRef(row.mission_id),
        asset_ref=AssetRef(row.asset_id),
        service_ref=None if row.service_id is None else ServiceRef(row.service_id),
        claim=row.claim,
        vulnerability_ids=tuple(row.vulnerability_ids_json),
        product=row.product,
        version=row.version,
        supporting_observation_refs=tuple(ObservationRef(ref) for ref in row.observation_refs_json),
        provenance=row.provenance,
        status=HypothesisStatus(row.status),
        created_at=row.created_at,
    )


def _attempt(row: ResearchAttemptRow) -> ResearchAttempt:
    return ResearchAttempt(
        attempt_ref=ResearchAttemptRef(row.attempt_id),
        hypothesis_ref=VulnerabilityHypothesisRef(row.hypothesis_id),
        provider_id=row.provider_id,
        request=ResearchRequest.model_validate(row.request_json),
        status=ResearchStatus(row.status),
        started_at=row.started_at,
        finished_at=row.finished_at,
        diagnostic=row.diagnostic,
    )


def _candidate(row: PoCCandidateRow) -> PoCCandidate:
    return PoCCandidate(
        candidate_ref=PoCCandidateRef(row.candidate_id),
        mission_ref=MissionRef(row.mission_id),
        hypothesis_ref=VulnerabilityHypothesisRef(row.hypothesis_id),
        source_identity=row.source_identity,
        source_class=SourceClass(row.source_class),
        source_uri=row.source_uri,
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
    )


def _hit(row: ResearchSourceHitRow) -> ResearchSourceHit:
    return ResearchSourceHit(
        hit_id=row.hit_id,
        attempt_ref=ResearchAttemptRef(row.attempt_id),
        candidate_ref=None if row.candidate_id is None else PoCCandidateRef(row.candidate_id),
        provider_id=row.provider_id,
        source=SourceHit.model_validate(row.source_json),
        source_identity=row.source_identity,
        decision=HitDecision(row.decision),
        decision_reason=row.decision_reason,
        observed_at=row.observed_at,
    )
