"""Add PlanningAttempt-owned interactions while preserving M15 Run-owned rows."""

import sqlalchemy as sa
from alembic import op

revision = "0015_m20_d6_planning_interactions"
down_revision = "0014_m20_d5_policy_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("interactions") as batch:
        batch.add_column(
            sa.Column("owner_kind", sa.String(32), nullable=False, server_default="CAPABILITY_RUN")
        )
        batch.add_column(sa.Column("planning_attempt_id", sa.String(255)))
        batch.add_column(sa.Column("purpose", sa.String(64)))
        batch.add_column(sa.Column("proposal_revision", sa.Integer()))
        batch.add_column(sa.Column("policy_decision_id", sa.String(255)))
        batch.alter_column("node_id", existing_type=sa.String(255), nullable=True)
        batch.alter_column("run_id", existing_type=sa.String(255), nullable=True)
        batch.create_check_constraint(
            "ck_interaction_owner",
            "(owner_kind = 'CAPABILITY_RUN' AND node_id IS NOT NULL AND run_id IS NOT NULL "
            "AND planning_attempt_id IS NULL AND purpose IS NULL AND proposal_revision IS NULL "
            "AND policy_decision_id IS NULL) OR "
            "(owner_kind = 'PLANNING_ATTEMPT' AND node_id IS NULL AND run_id IS NULL "
            "AND planning_attempt_id IS NOT NULL AND purpose IS NOT NULL "
            "AND proposal_revision IS NOT NULL)",
        )
    op.create_index("ix_interactions_attempt_id", "interactions", ["planning_attempt_id"])
    op.create_index(
        "uq_planning_assistance_context",
        "interactions",
        ["planning_attempt_id", "purpose", "proposal_revision"],
        unique=True,
        sqlite_where=sa.text("owner_kind = 'PLANNING_ATTEMPT' AND policy_decision_id IS NULL"),
    )
    op.create_index(
        "uq_planning_approval_context",
        "interactions",
        ["policy_decision_id"],
        unique=True,
        sqlite_where=sa.text("owner_kind = 'PLANNING_ATTEMPT' AND policy_decision_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_planning_approval_context", table_name="interactions")
    op.drop_index("uq_planning_assistance_context", table_name="interactions")
    op.drop_index("ix_interactions_attempt_id", table_name="interactions")
    with op.batch_alter_table("interactions") as batch:
        batch.drop_constraint("ck_interaction_owner", type_="check")
        batch.drop_column("policy_decision_id")
        batch.drop_column("proposal_revision")
        batch.drop_column("purpose")
        batch.drop_column("planning_attempt_id")
        batch.drop_column("owner_kind")
        batch.alter_column("node_id", existing_type=sa.String(255), nullable=False)
        batch.alter_column("run_id", existing_type=sa.String(255), nullable=False)
