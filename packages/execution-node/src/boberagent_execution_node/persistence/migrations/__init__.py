"""Alembic entry points for the independent Node runtime schema."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

from ..database import RuntimeDatabase


def _config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parent))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_database(database: RuntimeDatabase, revision: str = "head") -> None:
    config = _config(database.url)
    # SQLite batch-rebuilds referenced tables (E5-E widens a CHECK, not data).
    # Disable FK enforcement only on this dedicated migration connection BEFORE
    # the transaction. Validate both ends; ordinary sessions always retain FKs.
    with database.migration_engine.connect() as connection:
        if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
            raise RuntimeError("invalid Node foreign-key history")
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        try:
            with connection.begin():
                config.attributes["connection"] = connection
                command.upgrade(config, revision)
                if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
                    raise RuntimeError("Node migration violated foreign keys")
        finally:
            connection.rollback()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def current_revision(database: RuntimeDatabase) -> str | None:
    with database.migration_engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()
