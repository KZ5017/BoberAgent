"""Persist Node-owned Resource and Session lifecycle metadata.

Revision ID: 0004_resource_session_runtime
Revises: 0003_artifact_sync_metadata
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_resource_session_runtime"
down_revision: str | None = "0003_artifact_sync_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_timestamp = sa.String(length=32)


def upgrade() -> None:
    op.create_table(
        "runtime_resources",
        sa.Column("resource_id", sa.String(255), primary_key=True),
        sa.Column("resource_type", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(255), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("owner_ref", sa.String(255), nullable=False),
        sa.Column(
            "created_by_run",
            sa.String(255),
            sa.ForeignKey("runtime_runs.run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("updated_at", _timestamp, nullable=False),
        sa.Column("last_activity_at", _timestamp, nullable=False),
        sa.Column("access_modes_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", _timestamp),
        sa.Column("lifecycle_metadata_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_runtime_resources_owner_ref", "runtime_resources", ["owner_ref"])
    op.create_table(
        "runtime_sessions",
        sa.Column("session_id", sa.String(255), primary_key=True),
        sa.Column("session_type", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(255), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("owner_ref", sa.String(255), nullable=False),
        sa.Column(
            "created_by_run",
            sa.String(255),
            sa.ForeignKey("runtime_runs.run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("updated_at", _timestamp, nullable=False),
        sa.Column("last_activity_at", _timestamp, nullable=False),
        sa.Column("target_ref", sa.String(255)),
        sa.Column("identity_ref", sa.String(255)),
        sa.Column("access_context_ref", sa.String(255)),
        sa.Column("resource_refs_json", sa.JSON(), nullable=False),
        sa.Column("supported_operations_json", sa.JSON(), nullable=False),
        sa.Column("access_modes_json", sa.JSON(), nullable=False),
        sa.Column("lifecycle_metadata_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_runtime_sessions_owner_ref", "runtime_sessions", ["owner_ref"])
    op.create_index("ix_runtime_sessions_target_ref", "runtime_sessions", ["target_ref"])


def downgrade() -> None:
    op.drop_index("ix_runtime_sessions_target_ref", table_name="runtime_sessions")
    op.drop_index("ix_runtime_sessions_owner_ref", table_name="runtime_sessions")
    op.drop_table("runtime_sessions")
    op.drop_index("ix_runtime_resources_owner_ref", table_name="runtime_resources")
    op.drop_table("runtime_resources")
