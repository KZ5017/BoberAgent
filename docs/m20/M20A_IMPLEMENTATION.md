# M20-A research foundation and live repository metadata

`boberagent_core.research.CoreResearchService` admits one `VulnerabilityHypothesis` for a
Mission-owned Asset. Optional Service and supporting Observation refs are checked against
persisted Core ownership; the hypothesis is a research claim, not a Finding or World State fact.
Its only lifecycle states are `ACTIVE` and `RETIRED`; retired hypotheses cannot start research.

`ResearchProvider.search(ResearchRequest)` is an async, source-neutral port. Core constructs a
bounded request only from admitted hypothesis IDs, product/version and claim, with explicit source
classes, result limit (1–50) and optional date bounds. A provider cannot select another target.
M20-A keeps the injected deterministic provider and adds an opt-in live GitHub
repository-metadata adapter. A pending attempt is persisted before the call. `FOUND` means at
least one candidate was admitted;
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
a later-phase gate. M20-B owns acquisition and pinned source evidence.

Run the offline smoke with `uv run python scripts/manual-smoke/m20a_research_smoke_test.py`.

## GitHub repository metadata adapter (query mapping v1)

`GitHubResearchProvider` lives in Core research infrastructure and implements the existing
source-neutral `ResearchProvider.search()` port. Its provider ID is
`github-repository-search-v1`, which also identifies the deterministic outbound query mapping.
An operator can reconstruct the safe `q` value from the persisted `ResearchRequest` and
`github_repository_query(request)` for this version; no token or provider syntax is stored in
the domain request. The mapping uses the lexicographically first explicit CVE ID when present.
Otherwise, it takes the first admitted term with at least two informative ASCII words, retains
up to three, quotes that phrase, and adds `poc`. Search is limited to repository **name and
description**. Optional publication bounds map to GitHub repository `created:` dates; Core
still checks returned timestamps at full precision. Repository creation is not PoC publication.
An empty, unsupported, or over-256-character query is rejected before network access.

The adapter sends exactly one GET to `https://api.github.com/search/repositories` with
`page=1` and `per_page=ResearchRequest.result_limit` (at most 50). Production owns an
`httpx.AsyncClient` with redirects and ambient proxy configuration disabled. Config bounds HTTP
timeout, decoded response bytes, and User-Agent; the optional `SecretStr` token is placed only in
an Authorization header. It can be supplied by an operator entrypoint using the existing
`.env.local` convention; Core itself never loads CLI configuration. GitHub's authenticated and
unauthenticated search limits differ. Rate limiting, authentication, timeout, network failure,
oversized/malformed responses, and unsupported queries stop after one attempt with bounded
token-free diagnostics; there is **no automatic retry**.

Only public repository metadata from the search response is used: validated GitHub HTTPS URL,
repository ID/name/description, language, created/updated timestamps, and default branch.
A default branch is recorded as `branch:<name>`, a **mutable claim**, never a commit SHA or
acquired revision. Vulnerability IDs are extracted only from returned name/description;
product/version claims are not inferred from the query. Core's normal matching and deduplication
rules remain authoritative. `incomplete_results=true` becomes `PARTIAL` even with zero admitted
candidates. No clone, archive, README, file, contents API, code search, Artifact, Workspace,
ExecutionPlan, or execution occurs.

## Abandoned research attempts

A `STARTED` attempt is durable before the provider call. If Core dies, no result is known.
`CoreResearchService.reconcile_abandoned_attempts()` is an **explicit**, idempotent startup
operation; it changes only `STARTED` rows at least the maximum 120-second provider timeout plus
the default 30-second grace old to `INTERRUPTED`. The grace is injectable/testable. It preserves
the request and history, produces no hits/candidates, and does not retry. Observed provider
timeouts remain `PROVIDER_ERROR` with a distinct safe timeout diagnostic. Operator cancellation
has no separate M20-A API. Automatic reconciliation assumes **one active Core owner** for the
research database; concurrent owners need an owner/lease mechanism before automatic sweeping.
The status column is a string, so no migration is needed.

Run the offline smoke as above. For an explicit opt-in **live** metadata-only smoke, see
`scripts/manual-smoke/README.md`. M20-A ends with candidate leads; acquisition starts at M20-B.
