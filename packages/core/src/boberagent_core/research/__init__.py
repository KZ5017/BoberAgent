"""Public Core-owned M20-A research boundary."""

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
from .provider import DeterministicResearchProvider, ResearchProvider
from .service import (
    CoreResearchService,
    ResearchError,
    build_research_request,
    normalize_source_identity,
)

__all__ = [
    "CoreResearchService",
    "DeterministicResearchProvider",
    "HitDecision",
    "HypothesisStatus",
    "PoCCandidate",
    "PoCCandidateRef",
    "ResearchAttempt",
    "ResearchAttemptRef",
    "ResearchError",
    "ResearchProvider",
    "ResearchRequest",
    "ResearchResponseStatus",
    "ResearchResult",
    "ResearchSourceHit",
    "ResearchStatus",
    "SourceClass",
    "SourceHit",
    "VulnerabilityHypothesis",
    "VulnerabilityHypothesisRef",
    "build_research_request",
    "normalize_source_identity",
]
