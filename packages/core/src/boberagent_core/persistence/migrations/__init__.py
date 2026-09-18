"""Programmatic and command-line access to Core Alembic migrations."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection

from boberagent_core.persistence.database import CoreDatabase, DatabaseConfig


def alembic_config(database_url: str) -> Config:
    """Build Alembic configuration without relying on a process working directory."""

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parent))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_database(database: CoreDatabase, revision: str = "head") -> None:
    """Upgrade a Core database through explicit schema revisions."""

    config = alembic_config(database.config.url)
    with database._migration_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def current_revision(database: CoreDatabase) -> str | None:
    """Read the revision stamped in a migrated database."""

    with database._migration_engine.connect() as connection:
        return _revision_from_connection(connection)


def head_revision() -> str:
    """Return the single expected Core schema head without opening a database."""

    script = ScriptDirectory.from_config(alembic_config("sqlite+pysqlite:///:memory:"))
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("Core migration history has no head revision")
    return head


def _revision_from_connection(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def main(argv: Sequence[str] | None = None) -> None:
    """Run the intentionally small Core database administration CLI."""

    parser = argparse.ArgumentParser(description="BoberAgent Core database migrations")
    parser.add_argument("command", choices=("upgrade", "current"))
    parser.add_argument("--database-url", required=True)
    arguments = parser.parse_args(argv)

    database = CoreDatabase(DatabaseConfig(arguments.database_url))
    try:
        if arguments.command == "upgrade":
            upgrade_database(database)
        else:
            print(current_revision(database) or "unversioned")
    finally:
        database.dispose()
