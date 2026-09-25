# ADR 0013: M20 Research ownership and PoC candidate identity

**Status:** Accepted for the M20-A foundation.

## Context

M20 begins with research about one bounded security hypothesis for one selected Mission Asset.
Core currently owns Mission/Asset/Service/Observation meaning; the Capability Contract has no
`VulnerabilityHypothesis` or `PoCCandidate` model. External research is untrusted evidence, not
proof of target vulnerability and not permission to acquire or execute code. A research source
may repeat a hit, revise its claim, or expose a mutable repository URL before any content hash
exists. M20-A therefore needs explicit domain identity, provider ownership, bounded queries,
and durable provenance without choosing a specific public research backend first.

## Decision

### VulnerabilityHypothesis

Core owns a typed, Mission-scoped `VulnerabilityHypothesis`: one bounded security hypothesis for
one explicitly selected Mission-owned `AssetRef`. It may additionally reference a `ServiceRef`,
supporting `ObservationRef`s, known vulnerability identifiers, observed product/technology and
version evidence, a descriptive claim, and provenance. Its exact fields and persistence schema
are implementation details for M20-A. Core validates that the selected Asset belongs to the
Mission, any Service belongs to that Asset, and supporting Observations belong to the Mission.
Research must not change the selected target. `VulnerabilityHypothesis` is neither a `Finding`
nor a claim that the Mission target is vulnerable. It remains Core-owned; do not add it to the
shared Contract unless a later cross-component consumer demonstrably requires the domain object.

### ResearchProvider and admission

Core owns a source-neutral, typed `ResearchProvider` port. The conceptual flow is:

```text
VulnerabilityHypothesis
→ bounded ResearchRequest
→ ResearchProvider
→ sourced ResearchResult / candidate leads
→ Core admission
```

Research requests derive only explicitly admitted, non-secret terms from the selected
hypothesis. The contract supports bounded query terms, allowed source classes, a result limit,
and appropriate time/date constraints. Plaintext Secret/Credential values never enter queries.
Any advisory ranking occurs only after bounded retrieval. Core validates and admits provider
results; the provider does not mutate World State, create Findings, choose another target,
authorize acquisition, or authorize execution. Source-specific adapters remain replaceable.
M20-A begins with an injected deterministic provider/fake so domain, persistence, and admission
tests need no internet, API token, rate limit, GitHub dependency, or other external backend.

### PoCCandidate identity and history

`PoCCandidate` is a Core-owned research lead/reference with a stable Core-generated logical
`PoCCandidateRef`. Source or repository URL and content hash are **not** primary identity. A
separate normalized source/deduplication identity links repeated hits to one logical candidate
for the bounded hypothesis; individual provider hits, claims, timestamps, provenance, and
distinct revision claims remain historical records. M20-A must distinguish candidate found,
no match, partial result, provider error, duplicate source hit, and changed revision claim.
Exact ID-generation, normalization, lifecycle enum, and schema details remain for M20-A
implementation, but must preserve these semantics. A candidate is not acquired source, an
Artifact, an ExecutionPlan, or proof of a vulnerability.

## Consequences

- Core can persist and explain a candidate even when an external provider later changes its
  results or a repository branch moves. Acquisition in M20-B creates separately pinned evidence.
- M20-A may be unit/integration tested without external connectivity. Research-source failure is
  distinct from a sourced no-match result; neither proves the target safe or vulnerable.
- Core may use existing Mission/Asset/Service/Observation ownership data for bounded research.
  Full active-execution scope and PoC policy remain M20-D work; research ownership checks do not
  silently constitute execution authorization.
- No shared Contract change, production provider choice, or later M20 execution decision is made
  by this ADR.

## Rejected alternatives

- **Loose Goal parameters instead of a typed hypothesis:** too easy to lose target/evidence
  validation and confuse workflow intent with a vulnerability claim.
- **Immediate shared-Contract `VulnerabilityHypothesis`:** commits a Core-owned research concept
  across components before a cross-boundary need exists.
- **URL/repository URL as `PoCCandidateRef`:** mutable, aliasable, provider-dependent, and not a
  stable logical ID.
- **Content hash as pre-acquisition candidate ID:** bytes do not yet exist, and a candidate is
  not the acquired source revision.
- **Provider-specific domain models:** couple Core research meaning to one API or website.
- **Selecting the first live backend before the domain boundary:** makes the provider's API
  shape drive candidate identity, admission, and persistence.

## Deferred decisions

Choose the first live external provider, its adapter location/configuration, and its operational
egress/rate limits during M20-A live integration, not before the domain boundary exists. M20-B
owns acquisition mechanism, revision pinning, and archive/manifest format. M20-C owns inspection
models. M20-D owns ExecutionPlan changes and the PoC policy gate. M20-E/F own runtime isolation
and production `execute_plan()`. M20-G owns any stronger HITL restart semantics. M20-H later
selects an authorized real public PoC and lab target. None is resolved by this ADR.
