"""Add durable CapabilityResult semantic ingestion records.

Revision ID: 0005_result_ingestion
Revises: 0004_capability_registry
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_result_ingestion"
down_revision: str | None = "0004_capability_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_timestamp = sa.String(length=32)


def upgrade() -> None:
    op.create_table(
        "result_ingestions",
        sa.Column("run_id", sa.String(255), primary_key=True),
        sa.Column("result_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("transport_message_id", sa.String(255)),
        sa.Column("source_node_id", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("received_at", _timestamp, nullable=False),
        sa.Column("updated_at", _timestamp, nullable=False),
        sa.Column("processed_at", _timestamp),
        sa.Column("processing_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("materialized_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unsupported_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_conflict_fingerprint", sa.String(64)),
        sa.Column("last_conflict_at", _timestamp),
    )
    op.create_index("ix_result_ingestions_status", "result_ingestions", ["status"])
    op.create_index(
        "ix_result_ingestions_transport_message_id",
        "result_ingestions",
        ["transport_message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_result_ingestions_transport_message_id", table_name="result_ingestions")
    op.drop_index("ix_result_ingestions_status", table_name="result_ingestions")
    op.drop_table("result_ingestions")
