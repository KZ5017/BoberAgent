"""Add durable sequential Workflow definitions and Step Runs.

Revision ID: 0006_workflow_engine
Revises: 0005_result_ingestion
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_workflow_engine"
down_revision: str | None = "0005_result_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_timestamp = sa.String(length=32)


def upgrade() -> None:
    # Nullable definition data preserves the metadata-only Workflow rows created before M11.
    op.add_column("workflow_runs", sa.Column("definition_json", sa.JSON()))
    op.add_column("workflow_runs", sa.Column("failure_reason", sa.Text()))
    op.create_table(
        "workflow_step_runs",
        sa.Column(
            "workflow_run_id",
            sa.String(255),
            sa.ForeignKey("workflow_runs.workflow_run_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("step_id", sa.String(128), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("capability_id", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("inputs_json", sa.JSON(), nullable=False),
        sa.Column("success_policy", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "capability_run_id",
            sa.String(255),
            sa.ForeignKey("capability_runs.run_id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("updated_at", _timestamp, nullable=False),
        sa.Column("completed_at", _timestamp),
        sa.Column("failure_reason", sa.Text()),
        sa.UniqueConstraint("workflow_run_id", "position", name="uq_workflow_step_position"),
    )
    op.create_index("ix_workflow_step_runs_status", "workflow_step_runs", ["status"])
    op.create_index(
        "ix_workflow_step_runs_capability_run_id",
        "workflow_step_runs",
        ["capability_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_step_runs_capability_run_id", table_name="workflow_step_runs")
    op.drop_index("ix_workflow_step_runs_status", table_name="workflow_step_runs")
    op.drop_table("workflow_step_runs")
    op.drop_column("workflow_runs", "failure_reason")
    op.drop_column("workflow_runs", "definition_json")
