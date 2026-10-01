"""Core E3 durable import cursor; E2 permit history remains immutable."""

import sqlalchemy as sa
from alembic import op

revision = "0017_m20_e3_import_progress"
down_revision = "0016_m20_e2_preparation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "preparation_import_progress",
        sa.Column("import_id", sa.String(255), primary_key=True),
        sa.Column(
            "preparation_id",
            sa.String(255),
            sa.ForeignKey("runtime_preparation_attempts.preparation_id"),
            nullable=False,
        ),
        sa.Column("artifact_id", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("received_bytes", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(128)),
        sa.UniqueConstraint("preparation_id", "artifact_id", name="uq_preparation_import_artifact"),
        sa.CheckConstraint(
            "received_bytes >= 0 AND received_bytes <= size_bytes",
            name="ck_core_preparation_import_bounds",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING','IN_PROGRESS','VERIFIED','FAILED')",
            name="ck_core_preparation_import_state",
        ),
    )


def downgrade() -> None:
    op.drop_table("preparation_import_progress")
