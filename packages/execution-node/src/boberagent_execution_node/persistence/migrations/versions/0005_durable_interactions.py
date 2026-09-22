"""Add durable Node-owned human interactions.

Revision ID: 0005_durable_interactions
Revises: 0004_resource_session_runtime
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_durable_interactions"
down_revision: str | None = "0004_resource_session_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_timestamp = sa.String(length=32)


def upgrade() -> None:
    op.create_table(
        "runtime_interactions",
        sa.Column("interaction_id", sa.String(255), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(255),
            sa.ForeignKey("runtime_runs.run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("mission_id", sa.String(255), nullable=False),
        sa.Column("workflow_run_id", sa.String(255)),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON()),
        sa.Column("requested_at", _timestamp, nullable=False),
        sa.Column("responded_at", _timestamp),
        sa.Column("cancelled_at", _timestamp),
        sa.Column("cancellation_reason", sa.Text()),
    )
    op.create_index("ix_runtime_interactions_run_id", "runtime_interactions", ["run_id"])
    op.create_index("ix_runtime_interactions_state", "runtime_interactions", ["state"])


def downgrade() -> None:
    op.drop_index("ix_runtime_interactions_state", table_name="runtime_interactions")
    op.drop_index("ix_runtime_interactions_run_id", table_name="runtime_interactions")
    op.drop_table("runtime_interactions")
