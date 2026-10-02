"""Durable E4 preparation-owned source materialization state."""

import sqlalchemy as sa
from alembic import op

revision = "0007_preparation_materialization"
down_revision = "0006_preparation_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "preparation_materializations",
        sa.Column("preparation_id", sa.String(255), primary_key=True),
        sa.Column(
            "permit_id",
            sa.String(255),
            sa.ForeignKey("preparation_authorities.permit_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("run_id", sa.String(255), sa.ForeignKey("runtime_runs.run_id"), nullable=False),
        sa.Column("materialization_id", sa.String(255), nullable=False, unique=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("evidence_json", sa.JSON()),
        sa.Column("error_code", sa.String(128)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('INCOMPLETE', 'VERIFIED', 'PUBLISHED', 'QUARANTINED')",
            name="ck_preparation_materialization_state",
        ),
    )


def downgrade() -> None:
    op.drop_table("preparation_materializations")
