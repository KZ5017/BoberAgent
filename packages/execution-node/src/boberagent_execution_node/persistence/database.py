"""Node-local SQLite engine and transaction boundary."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session, sessionmaker


class RuntimeDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.url = f"sqlite+pysqlite:///{self.path}"
        self._engine = create_engine(self.url)
        event.listen(self._engine, "connect", _enable_foreign_keys)
        self._sessions = sessionmaker(bind=self._engine, expire_on_commit=False)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self._sessions() as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    @property
    def migration_engine(self) -> Engine:
        return self._engine

    def close(self) -> None:
        self._engine.dispose()


def _enable_foreign_keys(dbapi_connection: DBAPIConnection, _connection_record: object) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()
