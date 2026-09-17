"""Create the Milestone 4 Node runtime schema.

Revision ID: 0001_runtime_foundation
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_runtime_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_timestamp = sa.String(length=32)


def upgrade() -> None:
    op.create_table(
        "runtime_runs",
        sa.Column("run_id", sa.String(255), primary_key=True),
        sa.Column("mission_id", sa.String(255), nullable=False),
        sa.Column("capability_id", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("parent_run_id", sa.String(255)),
        sa.Column("workflow_run_id", sa.String(255)),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("started_at", _timestamp),
        sa.Column("finished_at", _timestamp),
        sa.Column("error_code", sa.String(255)),
    )
    op.create_table(
        "managed_processes",
        sa.Column("process_id", sa.String(255), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(255),
            sa.ForeignKey("runtime_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool", sa.String(255), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("argument_count", sa.Integer(), nullable=False),
        sa.Column("pid", sa.Integer()),
        sa.Column("started_at", _timestamp),
        sa.Column("finished_at", _timestamp),
        sa.Column("exit_code", sa.Integer()),
    )
    op.create_index("ix_managed_processes_run_id", "managed_processes", ["run_id"])
    op.create_table(
        "workspaces",
        sa.Column("workspace_id", sa.String(255), primary_key=True),
        sa.Column("owner_ref", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(255), nullable=False),
        sa.Column("isolation", sa.String(32), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("created_at", _timestamp, nullable=False),
    )
    op.create_index("ix_workspaces_owner_ref", "workspaces", ["owner_ref"])
    op.create_table(
        "artifact_spool",
        sa.Column("artifact_id", sa.String(255), primary_key=True),
        sa.Column("artifact_type", sa.String(255), nullable=False),
        sa.Column("storage_ref", sa.String(255), nullable=False),
        sa.Column(
            "run_id",
            sa.String(255),
            sa.ForeignKey("runtime_runs.run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(255)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("sync_state", sa.String(32), nullable=False),
    )
    op.create_index("ix_artifact_spool_run_id", "artifact_spool", ["run_id"])
    op.create_table(
        "event_outbox",
        sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(255), unique=True, nullable=False),
        sa.Column("event_json", sa.JSON(), nullable=False),
        sa.Column("delivery_state", sa.String(32), nullable=False),
        sa.Column("created_at", _timestamp, nullable=False),
    )
    op.create_table(
        "result_outbox",
        sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(255),
            sa.ForeignKey("runtime_runs.run_id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("delivery_state", sa.String(32), nullable=False),
        sa.Column("created_at", _timestamp, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("result_outbox")
    op.drop_table("event_outbox")
    op.drop_index("ix_artifact_spool_run_id", table_name="artifact_spool")
    op.drop_table("artifact_spool")
    op.drop_index("ix_workspaces_owner_ref", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_index("ix_managed_processes_run_id", table_name="managed_processes")
    op.drop_table("managed_processes")
    op.drop_table("runtime_runs")
