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
    with database.migration_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def current_revision(database: RuntimeDatabase) -> str | None:
    with database.migration_engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()
