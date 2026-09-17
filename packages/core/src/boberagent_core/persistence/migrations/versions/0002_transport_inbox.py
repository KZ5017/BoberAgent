"""Add durable transport inbox deduplication metadata.

Revision ID: 0002_transport_inbox
Revises: 0001_core_persistence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_transport_inbox"
down_revision: str | None = "0001_core_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_timestamp = sa.String(length=32)


def upgrade() -> None:
    op.create_table(
        "transport_inbox",
        sa.Column("message_id", sa.String(255), primary_key=True),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("message_kind", sa.String(32), nullable=False),
        sa.Column("correlation_id", sa.String(255), nullable=False),
        sa.Column("payload_id", sa.String(255), nullable=False),
        sa.Column("outbox_sequence", sa.Integer(), nullable=False),
        sa.Column("envelope_json", sa.JSON(), nullable=False),
        sa.Column("received_at", _timestamp, nullable=False),
        sa.Column("delivery_count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_transport_inbox_correlation_id", "transport_inbox", ["correlation_id"])
    op.create_index("ix_transport_inbox_kind", "transport_inbox", ["message_kind"])


def downgrade() -> None:
    op.drop_index("ix_transport_inbox_kind", table_name="transport_inbox")
    op.drop_index("ix_transport_inbox_correlation_id", table_name="transport_inbox")
    op.drop_table("transport_inbox")
