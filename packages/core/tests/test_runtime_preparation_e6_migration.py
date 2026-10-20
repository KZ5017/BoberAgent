"""Forward E6 schema upgrade preserves an existing E2 attempt and its immutable permit."""

from pathlib import Path

from alembic import command
from boberagent_core import current_revision, upgrade_database
from boberagent_core.persistence.migrations import alembic_config
from sqlalchemy import inspect
from test_runtime_preparation_e2 import _setup


def test_e6_upgrade_from_populated_e3_head(tmp_path: Path) -> None:
    database, _plan, _policy, _approval, _registry, admission, request = _setup(tmp_path)
    try:
        original = admission.admit(request)
        assert original.permit
        # In this isolated fixture all four new nullable E6 fields are empty. Remove
        # only the new revision to reproduce a populated previous-milestone database.
        config = alembic_config(database.config.url)
        with database._migration_engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0017_m20_e3_import_progress")
        assert current_revision(database) == "0017_m20_e3_import_progress"
        assert "completion_context_json" not in {
            c["name"]
            for c in inspect(database._migration_engine).get_columns("runtime_preparation_attempts")
        }
        upgrade_database(database)
        assert current_revision(database) == "0018_m20_e6_completion"
        with database.unit_of_work() as work:
            assert (
                work.runtime_preparations.get(original.attempt.preparation_ref) == original.attempt
            )
            assert (
                work.runtime_preparations.get_permit(original.permit.permit_ref) == original.permit
            )
            assert work.runs.get(original.permit.run_ref) is None  # Reserved != dispatched.
        upgrade_database(database)  # Repeat upgrade is non-destructive.
    finally:
        database.dispose()
