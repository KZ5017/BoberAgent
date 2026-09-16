"""Core-owned database configuration and transaction boundaries."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import sessionmaker

from .repositories import CoreUnitOfWork


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    """Validated configuration for the Milestone 2 SQLite database."""

    url: str
    echo: bool = False

    def __post_init__(self) -> None:
        backend = make_url(self.url).get_backend_name()
        if backend != "sqlite":
            raise ValueError("Milestone 2 Core persistence supports SQLite only")

    @classmethod
    def sqlite(cls, path: Path, *, echo: bool = False) -> DatabaseConfig:
        """Build a configuration for an explicit filesystem database path."""

        return cls(url=f"sqlite+pysqlite:///{path.resolve()}", echo=echo)


class CoreDatabase:
    """Own the SQLAlchemy engine and create explicit units of work.

    The public API intentionally yields repository collections, not raw SQLAlchemy sessions.
    Migrations are an explicit deployment action and are never replaced by ``create_all``.
    """

    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config
        self._engine = create_engine(config.url, echo=config.echo)
        event.listen(self._engine, "connect", _enable_sqlite_foreign_keys)
        self._sessions = sessionmaker(bind=self._engine, expire_on_commit=False)

    @contextmanager
    def unit_of_work(self) -> Iterator[CoreUnitOfWork]:
        """Commit one application transition atomically, or roll it back."""

        with self._sessions() as session:
            unit_of_work = CoreUnitOfWork(session)
            try:
                yield unit_of_work
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def dispose(self) -> None:
        """Release pooled database connections."""

        self._engine.dispose()

    @property
    def _migration_engine(self) -> Engine:
        """Provide the engine only to Core's migration adapter."""

        return self._engine


def _enable_sqlite_foreign_keys(
    dbapi_connection: DBAPIConnection, _connection_record: object
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()
