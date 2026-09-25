"""Bounded Core research and admission; no acquisition, dispatch, or World State writes."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from boberagent_contracts import AssetRef, MissionRef, ObservationRef, ServiceRef

from boberagent_core.clock import utc_now
from boberagent_core.persistence import CoreDatabase

from .models import (
    HitDecision,
    HypothesisStatus,
    PoCCandidate,
    PoCCandidateRef,
    ResearchAttempt,
    ResearchAttemptRef,
    ResearchRequest,
    ResearchResponseStatus,
    ResearchResult,
    ResearchSourceHit,
    ResearchStatus,
    SourceClass,
    SourceHit,
    VulnerabilityHypothesis,
    VulnerabilityHypothesisRef,
)
from .provider import ResearchProvider
from .repository import ResearchRepository


class ResearchError(ValueError):
    """A bounded Core research request or ownership check failed."""


def build_research_request(
    hypothesis: VulnerabilityHypothesis,
    *,
    allowed_source_classes: tuple[SourceClass, ...],
    result_limit: int,
    published_after: datetime | None = None,
    published_before: datetime | None = None,
) -> ResearchRequest:
    """Use only admitted hypothesis fields; never inspect unrelated Mission state."""

    terms = tuple(
        dict.fromkeys(
            (
                *hypothesis.vulnerability_ids,
                *(value for value in (hypothesis.product, hypothesis.version) if value),
                hypothesis.claim,
            )
        )
    )
    return ResearchRequest(
        hypothesis_ref=hypothesis.hypothesis_ref,
        mission_ref=hypothesis.mission_ref,
        asset_ref=hypothesis.asset_ref,
        service_ref=hypothesis.service_ref,
        query_terms=terms,
        vulnerability_ids=hypothesis.vulnerability_ids,
        allowed_source_classes=allowed_source_classes,
        result_limit=result_limit,
        published_after=published_after,
        published_before=published_before,
    )


def _normalize_public_url(source: str) -> str:
    if any(ord(character) < 32 for character in source):
        raise ResearchError("source URI contains control characters")
    try:
        parsed = urlsplit(source)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
        ):
            raise ResearchError("source URI must be an HTTP(S) URL without query or credentials")
        port = parsed.port
    except ValueError as error:
        raise ResearchError("source URI is malformed") from error
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    default_port = 443 if scheme == "https" else 80
    netloc = host if port is None or port == default_port else f"{host}:{port}"
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, "", ""))


def normalize_source_identity(hit: SourceHit) -> str:
    """Normalize URL aliases; revisions never enter identity.

    Both source and repository URLs must be credential/query-free. Accepted original URLs
    remain in the immutable hit history; malformed URLs are redacted before persistence.
    """

    source_uri = _normalize_public_url(hit.source_uri)
    source = (
        _normalize_public_url(hit.repository_identity)
        if hit.source_class is SourceClass.REPOSITORY and hit.repository_identity
        else source_uri
    )
    return f"{hit.source_class.value}:{source}"


def _matches(hypothesis: VulnerabilityHypothesis, hit: SourceHit) -> bool:
    ids = {value.casefold() for value in hypothesis.vulnerability_ids}
    if ids.intersection(value.casefold() for value in hit.vulnerability_ids):
        return True
    if hypothesis.product and hit.claimed_product and hit.match_excerpt:
        return hypothesis.product.casefold() == hit.claimed_product.casefold()
    return bool(hit.match_excerpt and hypothesis.claim.casefold() in hit.match_excerpt.casefold())


class CoreResearchService:
    """Own Mission validation, bounded requests, durable attempts, and candidate admission."""

    def __init__(self, database: CoreDatabase, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._database = database
        self._clock = clock

    def create_hypothesis(
        self,
        *,
        mission_ref: MissionRef,
        asset_ref: AssetRef,
        claim: str,
        provenance: str,
        service_ref: ServiceRef | None = None,
        vulnerability_ids: tuple[str, ...] = (),
        product: str | None = None,
        version: str | None = None,
        supporting_observation_refs: tuple[ObservationRef, ...] = (),
    ) -> VulnerabilityHypothesis:
        hypothesis = VulnerabilityHypothesis(
            hypothesis_ref=VulnerabilityHypothesisRef(f"hypothesis-{uuid4().hex}"),
            mission_ref=mission_ref,
            asset_ref=asset_ref,
            service_ref=service_ref,
            claim=claim,
            vulnerability_ids=vulnerability_ids,
            product=product,
            version=version,
            supporting_observation_refs=supporting_observation_refs,
            provenance=provenance,
            created_at=self._clock(),
        )
        with self._database.unit_of_work() as work:
            if work.missions.get(mission_ref) is None:
                raise ResearchError("Mission does not exist")
            asset = work.assets.get(asset_ref)
            if asset is None or asset.mission_ref != mission_ref:
                raise ResearchError("Asset does not belong to selected Mission")
            if service_ref is not None:
                service = work.services.get(service_ref)
                if service is None or service.asset_ref != asset_ref:
                    raise ResearchError("Service does not belong to selected Asset")
            for observation_ref in supporting_observation_refs:
                stored = work.observations.get(observation_ref)
                if stored is None:
                    raise ResearchError("supporting Observation does not exist")
                run = work.runs.get(stored.observation.run_ref)
                if run is None or run.mission_ref != mission_ref:
                    raise ResearchError("supporting Observation does not belong to Mission")
            work.research.add_hypothesis(hypothesis)
        return hypothesis

    def get_hypothesis(
        self, hypothesis_ref: VulnerabilityHypothesisRef
    ) -> VulnerabilityHypothesis | None:
        with self._database.unit_of_work() as work:
            return work.research.get_hypothesis(hypothesis_ref)

    def list_hypotheses(self, mission_ref: MissionRef) -> tuple[VulnerabilityHypothesis, ...]:
        with self._database.unit_of_work() as work:
            return work.research.list_hypotheses(str(mission_ref))

    def retire_hypothesis(self, hypothesis_ref: VulnerabilityHypothesisRef) -> None:
        with self._database.unit_of_work() as work:
            work.research.retire_hypothesis(hypothesis_ref)

    async def research(
        self,
        hypothesis_ref: VulnerabilityHypothesisRef,
        provider: ResearchProvider,
        *,
        allowed_source_classes: tuple[SourceClass, ...] = (SourceClass.REPOSITORY,),
        result_limit: int = 10,
        timeout_seconds: float = 30.0,
        published_after: datetime | None = None,
        published_before: datetime | None = None,
    ) -> ResearchAttempt:
        if not 0 < timeout_seconds <= 120:
            raise ResearchError("research timeout must be positive and at most 120 seconds")
        if not provider.provider_id or len(provider.provider_id) > 128:
            raise ResearchError("provider identity is invalid")
        with self._database.unit_of_work() as work:
            hypothesis = work.research.get_hypothesis(hypothesis_ref)
            if hypothesis is None:
                raise ResearchError("VulnerabilityHypothesis does not exist")
            if hypothesis.status is not HypothesisStatus.ACTIVE:
                raise ResearchError("VulnerabilityHypothesis is retired")
            request = build_research_request(
                hypothesis,
                allowed_source_classes=allowed_source_classes,
                result_limit=result_limit,
                published_after=published_after,
                published_before=published_before,
            )
            attempt = ResearchAttempt(
                attempt_ref=ResearchAttemptRef(f"research-attempt-{uuid4().hex}"),
                hypothesis_ref=hypothesis_ref,
                provider_id=provider.provider_id,
                request=request,
                status=ResearchStatus.STARTED,
                started_at=self._clock(),
            )
            work.research.add_attempt(attempt)
        try:
            response = ResearchResult.model_validate(
                await asyncio.wait_for(provider.search(request), timeout=timeout_seconds)
            )
            if len(response.hits) > request.result_limit:
                raise ResearchError("provider exceeded research result limit")
        except Exception:  # provider errors are safe, durable outcomes
            failed = attempt.model_copy(
                update={
                    "status": ResearchStatus.PROVIDER_ERROR,
                    "finished_at": self._clock(),
                    "diagnostic": "provider failed or returned an invalid bounded response",
                }
            )
            with self._database.unit_of_work() as work:
                work.research.finish_attempt(failed)
            return failed

        with self._database.unit_of_work() as work:
            admitted = sum(
                self._admit_hit(work.research, hypothesis, attempt, hit, request)
                for hit in response.hits
            )
            status = (
                ResearchStatus.PARTIAL
                if response.status is ResearchResponseStatus.PARTIAL
                else ResearchStatus.FOUND
                if admitted
                else ResearchStatus.NO_MATCH
            )
            finished = attempt.model_copy(
                update={
                    "status": status,
                    "finished_at": self._clock(),
                    "diagnostic": (
                        "provider reported partial result"
                        if response.status is ResearchResponseStatus.PARTIAL
                        else None
                    ),
                }
            )
            work.research.finish_attempt(finished)
        return finished

    def _admit_hit(
        self,
        repository: ResearchRepository,
        hypothesis: VulnerabilityHypothesis,
        attempt: ResearchAttempt,
        hit: SourceHit,
        request: ResearchRequest,
    ) -> bool:
        observed_at = self._clock()
        identity: str | None = None
        candidate_ref: PoCCandidateRef | None = None
        decision = HitDecision.REJECTED
        reason: str | None = None
        safe_hit = hit
        try:
            identity = normalize_source_identity(hit)
        except ResearchError:
            reason = "invalid source identity"
            # Malformed URLs may contain credentials or tokens; retain only a safe rejection.
            safe_hit = SourceHit(
                source_class=hit.source_class,
                source_uri="https://redacted.invalid/invalid-source",
            )
        if reason is None and hit.source_class not in request.allowed_source_classes:
            reason = "source class not allowed"
        if (
            reason is None
            and request.published_after
            and hit.published_at
            and hit.published_at < request.published_after
        ):
            reason = "source is older than requested publication window"
        if (
            reason is None
            and request.published_before
            and hit.published_at
            and hit.published_at > request.published_before
        ):
            reason = "source is newer than requested publication window"
        if reason is None and not _matches(hypothesis, hit):
            reason = "source claim does not match selected hypothesis"
        if reason is None:
            assert identity is not None
            existing = repository.candidate_by_source(hypothesis.hypothesis_ref, identity)
            if existing is None:
                candidate = PoCCandidate(
                    candidate_ref=PoCCandidateRef(f"poc-candidate-{uuid4().hex}"),
                    mission_ref=hypothesis.mission_ref,
                    hypothesis_ref=hypothesis.hypothesis_ref,
                    source_identity=identity,
                    source_class=hit.source_class,
                    source_uri=hit.source_uri,
                    first_seen_at=observed_at,
                    last_seen_at=observed_at,
                )
                repository.add_candidate(candidate)
                candidate_ref = candidate.candidate_ref
                decision = HitDecision.NEW
            else:
                candidate_ref = existing.candidate_ref
                repository.touch_candidate(candidate_ref, observed_at)
                decision = HitDecision.DUPLICATE
        repository.add_hit(
            ResearchSourceHit(
                hit_id=0,
                attempt_ref=attempt.attempt_ref,
                candidate_ref=candidate_ref,
                provider_id=attempt.provider_id,
                source=safe_hit,
                source_identity=identity,
                decision=decision,
                decision_reason=reason,
                observed_at=observed_at,
            )
        )

        return decision is not HitDecision.REJECTED

    def get_attempt(self, attempt_ref: ResearchAttemptRef) -> ResearchAttempt | None:
        with self._database.unit_of_work() as work:
            return work.research.get_attempt(attempt_ref)

    def list_attempts(
        self, hypothesis_ref: VulnerabilityHypothesisRef
    ) -> tuple[ResearchAttempt, ...]:
        with self._database.unit_of_work() as work:
            return work.research.list_attempts(hypothesis_ref)

    def list_hits(self, attempt_ref: ResearchAttemptRef) -> tuple[ResearchSourceHit, ...]:
        with self._database.unit_of_work() as work:
            return work.research.list_hits(attempt_ref)

    def get_candidate(self, candidate_ref: PoCCandidateRef) -> PoCCandidate | None:
        with self._database.unit_of_work() as work:
            return work.research.get_candidate(candidate_ref)

    def list_candidates(
        self, hypothesis_ref: VulnerabilityHypothesisRef
    ) -> tuple[PoCCandidate, ...]:
        with self._database.unit_of_work() as work:
            return work.research.list_candidates(hypothesis_ref)
