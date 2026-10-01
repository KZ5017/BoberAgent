"""Durable Core preparation request and immutable permit history; no runtime tables."""

import sqlalchemy as sa
from alembic import op

revision = "0016_m20_e2_preparation"
down_revision = "0015_m20_d6_planning_interactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_preparation_attempts",
        sa.Column("preparation_id", sa.String(255), primary_key=True),
        sa.Column(
            "mission_id", sa.String(255), sa.ForeignKey("missions.mission_id"), nullable=False
        ),
        sa.Column(
            "plan_id", sa.String(255), sa.ForeignKey("execution_plans.plan_id"), nullable=False
        ),
        sa.Column("plan_intent_sha256", sa.String(64), nullable=False),
        sa.Column("validation_decision_id", sa.String(255)),
        sa.Column("policy_decision_id", sa.String(255)),
        sa.Column("policy_context_sha256", sa.String(64)),
        sa.Column("approval_decision_id", sa.String(255)),
        sa.Column("acquisition_id", sa.String(255), nullable=False),
        sa.Column("raw_artifact_id", sa.String(255), nullable=False),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_artifact_id", sa.String(255), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("semantic_inspection_id", sa.String(255), nullable=False),
        sa.Column("semantic_sha256", sa.String(64), nullable=False),
        sa.Column("classification_inspection_id", sa.String(255), nullable=False),
        sa.Column("classification_sha256", sa.String(64), nullable=False),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("provider_version", sa.String(128)),
        sa.Column("provider_availability", sa.String(32)),
        sa.Column("provider_node_lifecycle", sa.String(32)),
        sa.Column("profile_id", sa.String(128), nullable=False),
        sa.Column("profile_version", sa.String(64), nullable=False),
        sa.Column("profile_sha256", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("reserved_run_id", sa.String(255)),
        sa.Column("permit_id", sa.String(255)),
        sa.Column("lifecycle", sa.String(32), nullable=False),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(128)),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("spec_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("request_fingerprint", name="uq_preparation_request_fingerprint"),
        sa.UniqueConstraint("reserved_run_id", name="uq_preparation_reserved_run"),
        sa.CheckConstraint("revision >= 0", name="ck_preparation_revision"),
        sa.CheckConstraint(
            "lifecycle IN ('REQUESTED','DISPATCHED','AWAITING_ARTIFACT','COMPLETED',"
            "'REJECTED','FAILED','INTERRUPTED','CANCELLED')",
            name="ck_preparation_lifecycle",
        ),
        sa.CheckConstraint(
            "(lifecycle = 'REJECTED' AND disposition = 'REJECTED' AND reason_code IS NOT NULL "
            "AND reserved_run_id IS NULL AND permit_id IS NULL AND terminal_at IS NOT NULL) OR "
            "(lifecycle = 'REQUESTED' AND disposition = 'ELIGIBLE' AND reason_code IS NULL "
            "AND reserved_run_id IS NOT NULL AND permit_id IS NOT NULL AND terminal_at IS NULL) OR "
            "(lifecycle IN ('DISPATCHED','AWAITING_ARTIFACT','COMPLETED','FAILED','INTERRUPTED',"
            "'CANCELLED') AND disposition = 'ELIGIBLE' AND reserved_run_id IS NOT NULL "
            "AND permit_id IS NOT NULL)",
            name="ck_preparation_e2_state",
        ),
    )
    op.create_table(
        "preparation_permits",
        sa.Column("permit_id", sa.String(255), primary_key=True),
        sa.Column(
            "preparation_id",
            sa.String(255),
            sa.ForeignKey("runtime_preparation_attempts.preparation_id"),
            nullable=False,
        ),
        sa.Column("reserved_run_id", sa.String(255), nullable=False),
        sa.Column("authority_sha256", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("permit_json", sa.JSON(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("preparation_id", name="uq_preparation_permit_attempt"),
        sa.UniqueConstraint("reserved_run_id", name="uq_preparation_permit_run"),
    )


def downgrade() -> None:
    op.drop_table("preparation_permits")
    op.drop_table("runtime_preparation_attempts")
