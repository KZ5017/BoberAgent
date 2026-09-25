# boberagent-core

Core owns BoberAgent's canonical assessment state. Milestone 2 provides a SQLite persistence
foundation, explicit repositories and the first deterministic `network.service` materializer. It
does not execute capabilities or implement workflow/goal behavior.

Milestone 8 adds the Core-owned Capability Registry and deterministic Router. A Capability is the
stable Contract ability; a provider is one Node's current implementation. Provider identity is a
UUID5 of `(node_id, capability_id)`, while implementation version remains mutable metadata. Node
handshakes refresh definitions, provider status, health, and `last_seen`; omitted capabilities are
retained as unavailable rather than deleted.

Persisted providers are marked `STALE` whenever a new Registry instance starts and remain
ineligible until refreshed. A five-minute, injectable freshness TTL provides an additional guard.
`READY` Nodes are eligible; `DEGRADED` Nodes are eligible only for specifically `AVAILABLE`
providers. Router v1 selects the lexicographically smallest eligible provider ID. Explicit Node or
provider constraints fail without fallback. Transport lifecycle integration explicitly marks a
disconnected Node stale; reconnecting and handshaking refreshes the same provider identities. Each
dispatch records the selected provider, Node, and
implementation version for the unchanged `CapabilityRunRef` before using the existing neutral
transport.

Milestone 5 adds a narrow transport receiving boundary. `CoreTransportReceiver` validates Event
and terminal Result envelopes and stores them in `transport_inbox` using stable message IDs.
Transport receipt still means only that a valid message was durably accepted. When configured
with `ResultIngestionService`, the receiver separately records the complete terminal Result before
semantic processing; transport acknowledgement is not a claim that World State materialization
succeeded.

## Result ingestion

`ResultIngestionService` owns the Milestone 9 semantic boundary. One canonical Result is stored per
`CapabilityRunRef`, together with a SHA-256 fingerprint of deterministic JSON and the lifecycle
`RECEIVED → PROCESSING → PROCESSED/PARTIALLY_PROCESSED`. Unknown Runs and provenance or identity
conflicts become `REJECTED`; unexpected Core-local processing errors become retryable `FAILED`
records. Identical redelivery returns the existing record. A different Result for the same Run is
never applied and increments durable conflict metadata without replacing the canonical envelope.

Processing validates the persisted Run and any routing decision, reconciles terminal execution
status without collapsing semantic outcome, merges compatible Artifact descriptors, appends
Observations immutably, and dispatches `ReducerRegistry` by Observation type. Unsupported
Observations are preserved as `UNSUPPORTED`; invalid known payloads are preserved as `REJECTED`.
Valid sibling Observations still materialize, leaving the Result `PARTIALLY_PROCESSED`. Findings,
Effects, Diagnostics, Resource descriptors, and Session descriptors remain auditable in the full
stored Result until dedicated reconciliation exists.

Artifact bytes remain independent of Result ingestion. A Result may establish metadata-only
catalog state before synchronization, or verified content may arrive first; reconciliation keeps
the same `ArtifactRef` and preserves content availability in both orders. `process_pending()`
recovers `RECEIVED`, interrupted `PROCESSING`, and retryable `FAILED` records after restart without
re-executing the capability.

## Database lifecycle

Construct `DatabaseConfig` with an explicit SQLite URL or `DatabaseConfig.sqlite(path)`, then run
the migration before opening application use cases:

```python
from pathlib import Path

from boberagent_core import CoreDatabase, DatabaseConfig, upgrade_database

database = CoreDatabase(DatabaseConfig.sqlite(Path("core.sqlite3")))
upgrade_database(database)
```

The equivalent administrative command is:

```text
uv run boberagent-core-db upgrade --database-url sqlite+pysqlite:///core.sqlite3
```

Tests always use isolated temporary files and upgrade them from zero through Alembic. Production
schema setup never uses `metadata.create_all()`.

## Ownership and reduction

SQLAlchemy rows and sessions are private persistence details. Application code uses
`CorePersistence` or an explicit `CoreDatabase.unit_of_work()` repository collection. Low-level
repository calls flush but do not commit, so a materialization and its Observation processing
status share one transaction.

The current API is synchronous and uses short-lived SQLAlchemy units of work; database access is
isolated behind this boundary so later asynchronous orchestration does not acquire ORM sessions.
There is no general Event Bus. A small Core event journal records replay-safe domain notifications
such as `credential.available`; it performs no delivery, scheduling, or workflow reaction. The
transport inbox remains separate and stores received envelopes for processing and acknowledgement.

The Registry and Router do not ingest received Results, select assessment strategy, or import
capability implementations. Result ingestion is a separate Core application service. Workflow
reasoning, background scheduling, and network transport remain separate concerns.

## Minimal Workflow Engine

Milestone 11 adds a Core-owned, explicitly pumped sequential Workflow state machine. A
`WorkflowDefinition` is immutable versioned intent containing ordered `WorkflowStepDefinition`
records. A `WorkflowRun` is one execution of that definition; each durable `WorkflowStepRun`
records its own lifecycle and its one-to-one `CapabilityRunRef`. The engine identifies capabilities
only by capability ID and operation, and dispatches exclusively through `CapabilityRouter`.

Step state progresses through `PENDING → PREPARED → ACTIVE → COMPLETED/FAILED`. Core persists the
CapabilityRun and `PREPARED` mapping before transport submission. A successfully submitted step is
`ACTIVE`; repeated `advance()` calls then wait for canonical Result Ingestion without dispatching
again. CapabilityRun identity is a deterministic UUID5 of `(WorkflowRunRef, step_id)`, so recovery
of the narrow pre-dispatch crash window may redeliver the same idempotent transport invocation but
cannot create a second logical Run. No failed capability is retried automatically.

The default `SUCCESS_ONLY` policy advances only for `COMPLETED + SUCCESS`.
`SUCCESS_OR_NEGATIVE` additionally accepts a definitive negative assessment, which is appropriate
for service discovery where zero open services is still a completed assessment. `PARTIAL`,
`UNKNOWN`, execution `FAILED`, `TIMED_OUT`, and `CANCELLED` fail the M11 sequential workflow. The
execution status and semantic outcome remain separately persisted in the canonical
`CapabilityResult`.

Mission and Asset records produce the same bounded mission/scope/entity projections used by direct
routed invocation. The Workflow Engine has no MCP, Node, tool, or capability-implementation
imports. M11 deliberately has no expression language, dynamic input binding, branching, loops,
parallel scheduling, background scheduler, remote cancellation protocol, Goal evaluator, or LLM.

## Durable human interaction

Core projects `interaction.requested` Events into an operator-facing Interaction table without
becoming the owner of the suspended capability coroutine. `CoreInteractionService` lists and
retrieves those records, persists an immutable response intent, validates it against the original
request, and sends it only through the neutral interaction transport. A lost acknowledgement is
safe: retry uses the exact persisted response, and the Node acknowledges an identical replay.

Confirmation, bounded non-secret text, and single-choice responses are supported. Different
second answers, invalid choices, wrong response shapes, and terminal or cancelled requests fail
explicitly. Response values are not copied into Events. Core restart preserves pending requests
and response intents; as long as the Node's original Run is still alive, a new Core process can
deliver the answer and resume it. Node restart is deliberately handled more conservatively as
described by ADR 0008.

## Artifact content

Milestone 6 adds a configurable managed filesystem store beside the SQLite Artifact catalog.
Incoming bytes are written under `incoming/` using hashed transfer identities, verified against the
declared size and SHA-256, then atomically published under `content/sha256/<prefix>/<digest>.blob`.
Node filenames and paths never select Core paths. Catalog state distinguishes metadata-only,
receiving, available, and failed content; only verified `AVAILABLE` bytes are exposed through
`CoreArtifactService`.

Incomplete transfers remain unavailable and resume from their durable offset after restart. A
published content file precedes the catalog commit, so a crash can leave only an unreferenced file,
never metadata claiming a partial file is complete. Logical Artifact identity remains independent
of content-addressed physical deduplication.

`network.service` uses `(AssetRef, normalized transport, port)` as endpoint identity. Its public
`ServiceRef` is a deterministic UUID5-derived logical reference. Replays add no duplicates. Every
contributing Observation remains in provenance, while the greatest `(observed_at, observation_id)`
deterministically supplies current state/product/version fields. This is deliberately a small
bootstrap conflict policy, not a generic confidence engine.

The resulting provenance chain is queryable without tool-specific knowledge:

```text
Service → ObservationRef → CapabilityRunRef → evidence ArtifactRef
```

Core understands the normalized `network.service` Observation vocabulary, not Nmap output or
capability implementation details.

`GoalRef` is Core-owned for now: Contract v1 does not exchange Goal objects, so adding a new
cross-package Contract identity would create semantics beyond this milestone.

## Secrets and Credentials

Milestone 16 keeps sensitive reusable values and authentication context distinct. `SecretMetadata`
contains a stable Mission-owned `SecretRef`, kind, lifecycle, timestamps, and provenance but never
the bytes. `Credential` contains safe account metadata plus named SecretRef bindings. The
`credential.candidate` reducer derives a deterministic Credential from a normalized Observation,
retains its source Observation/Artifact refs, and appends a durable `credential.available` event.

`CoreSecretService` is the only ordinary Core value boundary. Listing and lookup return metadata;
operator reveal and CapabilityRun grant issuance are explicit, Mission-checked, and recorded in a
non-sensitive access journal. SQLite stores the value as a BLOB and SQL parameters are hidden from
engine logs. The BLOB is not application-encrypted: host/database permissions, volume encryption,
and backup protection are deployment responsibilities for this bootstrap implementation.

Workflow steps can explicitly authorize CredentialRefs and SecretRefs. Core sends only their
bounded snapshots and short-lived values in the invocation projection. The Execution Node does not
persist those values. Raw Artifact evidence is never rewritten or redacted by credential
normalization, even when the evidence itself contains sensitive bytes. See ADR 0009.

## Bounded advisory Reasoner

Milestone 19 adds the public `boberagent_core.reasoning` API. A `ReasoningSelection` names one
Mission Goal and Asset plus optional Observation/Run refs, one active Procedure, selected canonical
Knowledge IDs, semantic hits, and advertised Capability IDs. `ContextBuilder` resolves those refs
through Core repositories and the Knowledge Router, preserving source IDs, versions, chunk order,
and provenance. The projection includes materialized Service metadata but does not load raw
Observation values, Artifact bytes, Goal parameters, or Secret values. It admits Goal/World State,
Procedure, attempts, canonical Knowledge, semantic Knowledge, then Capability metadata against a
deterministic character budget; included/omitted counts remain visible.

Selected Capability operations include their exact advertised inline input schemas as atomic,
lower-priority context entries. `ActionProposal.inputs` is required when a proposal exists;
proposal-level refs are distinct from operation inputs. Core does not infer or repair missing
inputs, and the authoritative operation schema remains the validator's final check.

`ReasonerProvider` is a separate async structured-generation contract, unrelated to embeddings.
The initial `OpenAICompatibleReasonerProvider` calls only `POST /v1/chat/completions` with
`response_format.type=json_schema`. Configure base URL, model ID, optional `SecretStr` bearer key,
timeout, temperature, and max output tokens explicitly at an application/operator boundary. The
provider itself never loads `.env.local`. An operator entrypoint may use the CLI's
`operator_environment(...)` to obtain `LM_API_TOKEN` and construct the provider; no such token is
required by Core or pytest.

`ReasoningService.interpret_and_propose(selection)` returns an `InterpretationResult`, optional
`ActionProposal`, provider/model metadata, and the exact bounded context/provenance used.
`ProposalValidator` rejects invented refs/operations, unavailable providers, out-of-Mission
targets, uncited sources, and inputs that fail the advertised inline JSON Schema. It never
dispatches: validation is **not** authorization, Workflow advancement, or Capability execution.
The provider has no tool-calling or MCP surface. No Decision persistence or autonomous planning was
added; see ADR 0012.
