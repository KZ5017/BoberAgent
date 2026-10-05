"""Immutable Resource-bound interpreter inspection history; READY remains forbidden."""

import sqlalchemy as sa
from alembic import op

revision = "0010_python_provenance"
down_revision = "0009_runtime_confinement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runtime_confinement_operations", sa.Column("input_sha256", sa.String(64)))
    op.create_table(
        "python_runtime_evidence",
        sa.Column(
            "operation_id",
            sa.String(255),
            sa.ForeignKey("python_resource_operations.operation_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "resource_id",
            sa.String(255),
            sa.ForeignKey("python_resource_details.resource_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("binding_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
    )
    for action in ("UPDATE", "DELETE"):
        op.execute(f"""CREATE TRIGGER python_evidence_no_{action.lower()}
            BEFORE {action} ON python_runtime_evidence
            BEGIN SELECT RAISE(ABORT, 'runtime evidence is immutable'); END""")


def downgrade() -> None:
    op.execute("DROP TRIGGER python_evidence_no_update")
    op.execute("DROP TRIGGER python_evidence_no_delete")
    op.drop_table("python_runtime_evidence")
    op.drop_column("runtime_confinement_operations", "input_sha256")
