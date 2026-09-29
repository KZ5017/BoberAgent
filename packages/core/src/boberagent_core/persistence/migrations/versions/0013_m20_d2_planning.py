"""M20-D2 immutable planning history and atomic reusable request identity."""

import sqlalchemy as sa
from alembic import op

revision = "0013_m20_d2_planning"
down_revision = "0012_m20_c1_inspection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planning_attempts",
        sa.Column("attempt_id", sa.String(255), primary_key=True),
        sa.Column(
            "mission_id", sa.String(255), sa.ForeignKey("missions.mission_id"), nullable=False
        ),
        sa.Column(
            "hypothesis_id",
            sa.String(255),
            sa.ForeignKey("vulnerability_hypotheses.hypothesis_id"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.String(255),
            sa.ForeignKey("poc_candidates.candidate_id"),
            nullable=False,
        ),
        sa.Column(
            "acquisition_id",
            sa.String(255),
            sa.ForeignKey("poc_acquisitions.acquisition_id"),
            nullable=False,
        ),
        sa.Column(
            "semantic_inspection_id",
            sa.String(255),
            sa.ForeignKey("poc_inspections.inspection_id"),
            nullable=False,
        ),
        sa.Column(
            "classification_inspection_id",
            sa.String(255),
            sa.ForeignKey("poc_inspections.inspection_id"),
            nullable=False,
        ),
        sa.Column("semantic_sha256", sa.String(64), nullable=False),
        sa.Column("classification_sha256", sa.String(64), nullable=False),
        sa.Column("planner_profile", sa.String(128), nullable=False),
        sa.Column("planner_version", sa.String(128), nullable=False),
        sa.Column("policy_profile", sa.String(128), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("history_json", sa.JSON(), nullable=False),
        sa.Column("lifecycle", sa.String(32), nullable=False),
        sa.Column("disposition", sa.String(32)),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(128)),
        sa.Column("diagnostic_codes_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("completed_at", sa.String(32)),
        sa.CheckConstraint("revision_number >= 0", name="ck_planning_revision"),
        sa.CheckConstraint(
            "lifecycle IN ('REQUESTED','EVALUATING','WAITING_INPUT','COMPLETED','FAILED','INTERRUPTED','CANCELLED')",
            name="ck_planning_lifecycle",
        ),
        sa.CheckConstraint(
            "disposition IS NULL OR disposition IN ('VALID','REQUIRES_INPUT','UNSUPPORTED','INVALID')",
            name="ck_planning_disposition",
        ),
        sa.CheckConstraint(
            "(lifecycle IN ('COMPLETED','FAILED','INTERRUPTED','CANCELLED')) = (completed_at IS NOT NULL)",
            name="ck_planning_completion_time",
        ),
        sa.CheckConstraint(
            "lifecycle != 'COMPLETED' OR disposition IS NOT NULL",
            name="ck_planning_completed_disposition",
        ),
        sa.CheckConstraint(
            "disposition != 'VALID' OR lifecycle = 'COMPLETED'", name="ck_planning_valid_terminal"
        ),
    )
    op.create_index(
        "uq_planning_attempt_reusable_request",
        "planning_attempts",
        ["request_fingerprint"],
        unique=True,
        sqlite_where=sa.text("lifecycle IN ('REQUESTED','EVALUATING','WAITING_INPUT','COMPLETED')"),
    )
    op.create_table(
        "execution_plans",
        sa.Column("plan_id", sa.String(255), primary_key=True),
        sa.Column(
            "mission_id", sa.String(255), sa.ForeignKey("missions.mission_id"), nullable=False
        ),
        sa.Column(
            "attempt_id",
            sa.String(255),
            sa.ForeignKey("planning_attempts.attempt_id"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("intent_sha256", sa.String(64), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("supersedes_plan_id", sa.String(255), sa.ForeignKey("execution_plans.plan_id")),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("attempt_id", name="uq_execution_plan_attempt"),
    )
    op.create_index("ix_execution_plan_intent", "execution_plans", ["intent_sha256"])
    op.create_table(
        "plan_decisions",
        sa.Column("decision_id", sa.String(255), primary_key=True),
        sa.Column(
            "plan_id", sa.String(255), sa.ForeignKey("execution_plans.plan_id"), nullable=False
        ),
        sa.Column("intent_sha256", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("evaluator_profile", sa.String(128), nullable=False),
        sa.Column("evaluator_version", sa.String(128), nullable=False),
        sa.Column("context_fingerprint", sa.String(64), nullable=False),
        sa.Column("record_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "kind IN ('VALIDATION','POLICY','APPROVAL')", name="ck_plan_decision_kind"
        ),
    )
    op.create_index(
        "ix_plan_decision_context", "plan_decisions", ["plan_id", "context_fingerprint"]
    )
    for table in ("execution_plans", "plan_decisions"):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {table}_immutable_{operation.lower()} BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'immutable planning history'); END"
                )
            )
    op.execute(
        sa.text(
            "CREATE TRIGGER planning_attempt_terminal BEFORE UPDATE ON planning_attempts "
            "WHEN OLD.lifecycle IN ('COMPLETED','FAILED','INTERRUPTED','CANCELLED') "
            "BEGIN SELECT RAISE(ABORT, 'immutable terminal planning attempt'); END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER planning_attempt_history BEFORE DELETE ON planning_attempts "
            "BEGIN SELECT RAISE(ABORT, 'immutable planning history'); END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER planning_attempt_identity BEFORE UPDATE ON planning_attempts WHEN "
            "OLD.attempt_id != NEW.attempt_id OR OLD.mission_id != NEW.mission_id OR "
            "OLD.hypothesis_id != NEW.hypothesis_id OR OLD.candidate_id != NEW.candidate_id OR "
            "OLD.acquisition_id != NEW.acquisition_id OR "
            "OLD.semantic_inspection_id != NEW.semantic_inspection_id OR "
            "OLD.classification_inspection_id != NEW.classification_inspection_id OR "
            "OLD.semantic_sha256 != NEW.semantic_sha256 OR OLD.classification_sha256 != NEW.classification_sha256 OR "
            "OLD.planner_profile != NEW.planner_profile OR OLD.planner_version != NEW.planner_version OR "
            "OLD.policy_profile != NEW.policy_profile OR OLD.policy_version != NEW.policy_version OR "
            "OLD.request_fingerprint != NEW.request_fingerprint OR OLD.request_json != NEW.request_json OR "
            "OLD.schema_version != NEW.schema_version OR OLD.created_at != NEW.created_at "
            "BEGIN SELECT RAISE(ABORT, 'immutable planning request'); END"
        )
    )


def downgrade() -> None:
    for table in ("plan_decisions", "execution_plans", "planning_attempts"):
        op.drop_table(table)
