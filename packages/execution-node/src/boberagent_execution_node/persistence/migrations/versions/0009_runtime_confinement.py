"""Append-only mechanism evidence and interrupted-operation reconciliation."""

import sqlalchemy as sa
from alembic import op

revision = "0009_runtime_confinement"
down_revision = "0008_python_resource_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_confinement_operations",
        sa.Column("operation_id", sa.String(255), primary_key=True),
        sa.Column("probe", sa.String(32), nullable=False),
        sa.Column("limits_json", sa.JSON(), nullable=False),
        sa.Column("boot_generation", sa.String(255), nullable=False),
        sa.Column("host_boot", sa.String(64), nullable=False),
        sa.Column("parent_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("evidence_json", sa.JSON()),
        sa.CheckConstraint(
            "state IN ('RUNNING','FINISHED','INTERRUPTED')", name="ck_confinement_state"
        ),
    )
    op.execute("""CREATE TRIGGER confinement_terminal_immutable
        BEFORE UPDATE ON runtime_confinement_operations
        WHEN OLD.state != 'RUNNING'
        BEGIN SELECT RAISE(ABORT, 'terminal confinement history is immutable'); END""")


def downgrade() -> None:
    op.execute("DROP TRIGGER confinement_terminal_immutable")
    op.drop_table("runtime_confinement_operations")
