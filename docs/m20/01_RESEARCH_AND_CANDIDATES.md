# M20-A — Bounded research and PoC candidates

## Goal and dependency

Start from a **specific** Core-owned `VulnerabilityHypothesis`, not an open-ended search for a
compromisable target. M20-A precedes acquisition; it must be independently useful when no PoC is
found. Existing Core Mission/Asset/Service/Observation state and M17/18 Knowledge are read-only
inputs. No actual research provider is selected or implemented by this document.

## Typed boundary

| Input | Output |
| --- | --- |
| `VulnerabilityHypothesis`: `MissionRef`, one selected `AssetRef`, optional `ServiceRef`, supporting `ObservationRef`s, observed technology/product and version evidence, vulnerability identifier **or** descriptive claim, provenance | Bounded `ResearchRequest`, sourced `ResearchResult`/provider-hit history, zero or more `PoCCandidate`s, distinct no-match/partial/provider-error state |

The initial Core schema need not pretend that a full Vulnerability ontology is already
materialized. `VulnerabilityHypothesis` is a typed, Mission-owned bounded hypothesis, not a
`Finding` or a `PoCCandidate`. Core validates that the selected Asset belongs to the Mission,
any Service belongs to that Asset, and supporting Observations belong to the Mission. Research
cannot change the selected Asset. Missing version evidence is unknown, not invented from a
search result. These ownership checks do not replace later active-execution scope/policy checks.

Core owns `ResearchProvider` as a typed, source-neutral port for bounded requests and sourced
results. Begin M20-A with an injected deterministic provider/fake; the first live adapter is
selected only during live integration. Future adapters may use GitHub, web search, vendor
advisories, CVE feeds, articles, or curated Knowledge without changing the domain. A
`ResearchRequest` derives only explicitly admitted non-secret terms from the selected hypothesis
and supports allowed source classes, a result limit, bounded query terms, and time/date limits
where appropriate. It never contains plaintext Secret/Credential values. Core, not the provider,
admits candidate leads. Advisory ranking occurs only after bounded retrieval; a provider hit is
untrusted evidence, not acquisition or execution authority.

Planned `PoCCandidate` responsibilities: stable Core-generated `PoCCandidateRef`, hypothesis link,
separate normalized source/deduplication identity, provider and source type, canonical source URI
and repository identity when relevant, advertised revision or
commit candidate, vulnerability IDs and claimed affected product/version, runtime/entrypoint
hints, publication/update metadata when supplied, source provenance, match evidence and
uncertainty, acquisition state. Distinguish provider claim from Core-observed fact. Source URL,
repository URL, and pre-acquisition content hash are not candidate identity. Preserve each
query/provider hit, timestamp, duplicate hit, and distinct revision claim so the candidate can
be explained after a provider changes its results.

Candidate matching should require traceable correspondence to the selected hypothesis, e.g.
explicit vulnerability ID or product/version claim plus source excerpt/metadata. Prefer bounded
deterministic filters; the M19 Reasoner may advise among ambiguous hits but cannot turn a weak
match into target proof. A selected candidate remains a reference until M20-B acquires and pins
content. Persist candidate lifecycle and research attempts under Core ownership with stable IDs;
repeat the same request safely without uncontrolled candidate duplicates. Preserve candidate
found, no match, partial result, provider error, duplicate hit, and changed revision claim as
distinct states/history. A provider failure or sourced no-match does not prove target safety.

## Reuse, additions, and non-goals

Reuse typed Mission refs, World State queries, current Knowledge router for curated context, and
M19's *advisory* provider pattern. Add only a Core-owned hypothesis/candidate/research record and
provider interface/adapter boundary when M20-A is implemented. Source-specific HTTP/API details
belong in adapters, not Contracts or World State reducers. The existing M11 Workflow cannot yet
represent dynamic candidate fan-out; no new orchestration path is implied here.

No arbitrary vulnerability discovery, broad internet crawl, PoC download, executable import,
automatic Finding, global Knowledge ingestion, or capability execution belongs to M20-A.

## Stop, security, and tests

Reject out-of-Mission/unknown refs before contacting a provider. Stop on missing hypothesis,
unbounded search request, unsupported provider, malformed provenance, or exhausted result limit.
Preserve partial sourced hits on provider failure without treating them as trusted candidates.
Untrusted titles/snippets are data; never follow their instructions or leak Secrets in queries.

Tests should cover typed input/ownership, bounded query projection, zero/multiple hits, stable
candidate identity, duplicate research, conflicting source claims, provider failure/timeout,
uncertain version matching, provenance, redaction, and the absence of acquisition/execution.
Manual validation may inspect public metadata for an explicitly chosen lab hypothesis; it must
not fetch or run code yet. **Done** when a fresh Core process can reload a sourced candidate and
explain why it matched the original hypothesis, while no Artifact is executable.

The Core ownership, `VulnerabilityHypothesis`, provider port, bounded query/admission rule, and
candidate logical-identity semantics are accepted in
[ADR 0013](../adr/0013-m20-research-ownership-and-candidate-identity.md). Exact model fields,
identity generation, dedup normalization, and lifecycle schema remain M20-A implementation
details. **Deferred to M20-A live integration:** first external provider, concrete adapter
location/configuration, and operational egress/rate limits. Do not make the domain GitHub-specific
or bypass Mission ownership.

The deterministic M20-A foundation is implemented. Its concrete lifecycle, request/admission
rules, source normalization and smoke command are recorded in [M20-A implementation](M20A_IMPLEMENTATION.md).
