# boberagent-core

Core owns BoberAgent's canonical assessment state. Milestone 2 provides a SQLite persistence
foundation, explicit repositories and the first deterministic `network.service` materializer. It
does not execute capabilities or implement workflow/goal behavior.

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
No event table is created because Milestone 2 has no event-delivery use case yet.

`network.service` uses `(AssetRef, normalized transport, port)` as endpoint identity. Its public
`ServiceRef` is a deterministic UUID5-derived logical reference. Replays add no duplicates. Every
contributing Observation remains in provenance, while the greatest `(observed_at, observation_id)`
deterministically supplies current state/product/version fields. This is deliberately a small
bootstrap conflict policy, not a generic confidence engine.

`GoalRef` is Core-owned for now: Contract v1 does not exchange Goal objects, so adding a new
cross-package Contract identity would create semantics beyond this milestone.
