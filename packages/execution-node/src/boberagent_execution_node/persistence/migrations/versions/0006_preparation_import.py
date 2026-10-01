"""Node-owned preparation admission and immutable imported Artifact identities."""

import sqlalchemy as sa
from alembic import op

revision = "0006_preparation_import"
down_revision = "0005_durable_interactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "preparation_authorities",
        sa.Column("permit_id", sa.String(255), primary_key=True),
        sa.Column("preparation_id", sa.String(255), nullable=False, unique=True),
        sa.Column(
            "run_id",
            sa.String(255),
            sa.ForeignKey("runtime_runs.run_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("authority_sha256", sa.String(64), nullable=False),
        sa.Column("principal_id", sa.String(255), nullable=False),
        sa.Column("permit_json", sa.JSON(), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "preparation_imports",
        sa.Column("import_id", sa.String(255), primary_key=True),
        sa.Column(
            "permit_id",
            sa.String(255),
            sa.ForeignKey("preparation_authorities.permit_id"),
            nullable=False,
        ),
        sa.Column("artifact_id", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("received_bytes", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(128)),
        sa.CheckConstraint(
            "size_bytes >= 0 AND received_bytes >= 0 AND received_bytes <= size_bytes",
            name="ck_preparation_import_bounds",
        ),
        sa.CheckConstraint(
            "state IN ('PARTIAL', 'VERIFIED', 'FAILED')", name="ck_preparation_import_state"
        ),
    )
    op.create_table(
        "imported_artifacts",
        sa.Column("artifact_id", sa.String(255), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_key", sa.String(64), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("imported_artifacts")
    op.drop_table("preparation_imports")
    op.drop_table("preparation_authorities")
