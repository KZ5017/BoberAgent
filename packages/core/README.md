# boberagent-core

Core owns BoberAgent's canonical assessment state. Milestone 2 provides a SQLite persistence
foundation, explicit repositories and the first deterministic `network.service` materializer. It
does not execute capabilities or implement workflow/goal behavior.

Milestone 5 adds a narrow transport receiving boundary. `CoreTransportReceiver` validates Event
and terminal Result envelopes and stores them in `transport_inbox` using stable message IDs. This
is delivery/deduplication metadata only: receiving a Result does not create Runs, Artifacts,
Observations, materialized World State, Event Bus activity, or workflow reactions.

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
No general Event Bus table exists. The transport inbox stores received envelopes for later
processing and acknowledgement without interpreting their assessment meaning.

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

`GoalRef` is Core-owned for now: Contract v1 does not exchange Goal objects, so adding a new
cross-package Contract identity would create semantics beyond this milestone.
