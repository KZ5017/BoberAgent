# M20-A deterministic research foundation

`boberagent_core.research.CoreResearchService` admits one `VulnerabilityHypothesis` for a
Mission-owned Asset. Optional Service and supporting Observation refs are checked against
persisted Core ownership; the hypothesis is a research claim, not a Finding or World State fact.
Its only lifecycle states are `ACTIVE` and `RETIRED`; retired hypotheses cannot start research.

`ResearchProvider.search(ResearchRequest)` is an async, source-neutral port. Core constructs a
bounded request only from admitted hypothesis IDs, product/version and claim, with explicit source
classes, result limit (1–50) and optional date bounds. A provider cannot select another target.
M20-A includes only an injected deterministic provider, not an internet adapter. A pending
attempt is persisted before the call. `FOUND` means at least one candidate was admitted;
`NO_MATCH` also covers returned hits all rejected by admission; `PARTIAL` retains sourced hits;
`PROVIDER_ERROR` records a safe diagnostic without copying upstream exception text.

Each provider hit is recorded with its request/attempt, provider, timestamp, admission decision,
and claimed revision. Core admits a hit only when its source class is allowed and its claim
matches the selected hypothesis by an explicit vulnerability ID, or by exact claimed product
plus a source excerpt, or by the full hypothesis claim in an excerpt. Provider claims are not
target proof. Invalid URLs are rejected and redacted in the durable rejection record.

Candidates have Core-generated `PoCCandidateRef`s. The unique dedup key is **hypothesis ref +
source class + normalized source identity**. Repository identity is preferred for repository
hits, otherwise source URI is used. Normalization lowercases scheme/host, removes default ports,
trailing slash aliases and fragments; URLs with user-info or queries are rejected. Revision is
never part of identity. Repeated hits and changed revisions remain separate historical hit rows;
the candidate's logical ID remains unchanged. Different hypotheses have distinct candidates.

No PoC bytes are fetched, no Artifact/Workspace/ExecutionPlan is created, no capability is
dispatched, and no target Observation/Finding is written. Active execution scope/policy remains
a later-phase gate. Real research provider choice, egress controls and rate limits are the
deferred M20-A live-integration step. M20-B owns acquisition and pinned source evidence.

Run the offline smoke with `uv run python scripts/manual-smoke/m20a_research_smoke_test.py`.
