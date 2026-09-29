"""At most one immutable D5 policy assessment per exact decision context."""

import sqlalchemy as sa
from alembic import op

revision = "0014_m20_d5_policy_identity"
down_revision = "0013_m20_d2_planning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_plan_policy_context",
        "plan_decisions",
        ["plan_id", "kind", "context_fingerprint"],
        unique=True,
        # D2 allowed multiple historical policy variants under one context.
        # Only versioned D5 checker records carry this evaluator identity.
        sqlite_where=sa.text(
            "kind = 'POLICY' AND json_extract(record_json, '$.document.value.evaluator_profile') = 'm20-d5-policy-evaluator'"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_plan_policy_context", table_name="plan_decisions")
