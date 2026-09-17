"""Add Core Capability provider registry and routing provenance.

Revision ID: 0004_capability_registry
Revises: 0003_artifact_content
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_capability_registry"
down_revision: str | None = "0003_artifact_content"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_timestamp = sa.String(length=32)


def upgrade() -> None:
    op.create_table(
        "capability_providers",
        sa.Column("provider_id", sa.String(36), primary_key=True),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("capability_id", sa.String(255), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("implementation_version", sa.String(64), nullable=False),
        sa.Column("reported_status", sa.String(32), nullable=False),
        sa.Column("availability", sa.String(32), nullable=False),
        sa.Column("first_registered_at", _timestamp, nullable=False),
        sa.Column("last_seen_at", _timestamp, nullable=False),
        sa.Column("node_lifecycle", sa.String(32), nullable=False),
        sa.Column("node_database_ready", sa.Boolean(), nullable=False),
        sa.Column("node_degraded_reasons_json", sa.JSON(), nullable=False),
        sa.Column("unavailability_reason", sa.Text()),
        sa.UniqueConstraint(
            "node_id",
            "capability_id",
            name="uq_capability_provider_identity",
        ),
    )
    op.create_index(
        "ix_capability_providers_capability_id",
        "capability_providers",
        ["capability_id"],
    )
    op.create_index(
        "ix_capability_providers_node_id",
        "capability_providers",
        ["node_id"],
    )
    op.create_table(
        "capability_routing_decisions",
        sa.Column("run_id", sa.String(255), primary_key=True),
        sa.Column("capability_id", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("capability_providers.provider_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("implementation_version", sa.String(64), nullable=False),
        sa.Column("selected_at", _timestamp, nullable=False),
    )
    op.create_index(
        "ix_capability_routing_provider_id",
        "capability_routing_decisions",
        ["provider_id"],
    )
    op.create_index(
        "ix_capability_routing_node_id",
        "capability_routing_decisions",
        ["node_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_capability_routing_node_id", table_name="capability_routing_decisions")
    op.drop_index("ix_capability_routing_provider_id", table_name="capability_routing_decisions")
    op.drop_table("capability_routing_decisions")
    op.drop_index("ix_capability_providers_node_id", table_name="capability_providers")
    op.drop_index("ix_capability_providers_capability_id", table_name="capability_providers")
    op.drop_table("capability_providers")
