"""Durable E5-E evidence and pre-F VERIFYING phase; READY stays forbidden."""

import sqlalchemy as sa
from alembic import op

revision = "0011_empty_python_environment"
down_revision = "0010_python_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rebuild with FK checking disabled only by the migration runner's existing
    # SQLite batch support. Immutable/READY triggers are explicitly retained.
    op.execute("DROP TRIGGER python_resource_immutable_binding")
    with op.batch_alter_table("python_resource_details") as batch:
        batch.drop_constraint("ck_python_b_phase", type_="check")
        batch.create_check_constraint(
            "ck_python_e_phase",
            "phase IN ('RESERVED','BUILDING','VERIFYING','QUARANTINED','REMOVED')",
        )
    op.execute("""CREATE TRIGGER python_resource_immutable_binding
        BEFORE UPDATE ON python_resource_details
        WHEN OLD.resource_id != NEW.resource_id OR OLD.preparation_id != NEW.preparation_id
          OR OLD.permit_id != NEW.permit_id OR OLD.request_sha256 != NEW.request_sha256
          OR OLD.request_json != NEW.request_json OR OLD.baseline_json != NEW.baseline_json
          OR OLD.workspace_correlation != NEW.workspace_correlation
        BEGIN SELECT RAISE(ABORT, 'immutable Python Resource reservation'); END""")
    op.create_table(
        "python_environment_constructions",
        sa.Column(
            "resource_id",
            sa.String(255),
            sa.ForeignKey("python_resource_details.resource_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "operation_id",
            sa.String(255),
            sa.ForeignKey("python_resource_operations.operation_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
    )
    for action in ("UPDATE", "DELETE"):
        op.execute(f"""CREATE TRIGGER python_environment_no_{action.lower()}
            BEFORE {action} ON python_environment_constructions
            BEGIN SELECT RAISE(ABORT, 'environment evidence is immutable'); END""")
    for action in ("INSERT", "UPDATE"):
        op.execute(f"""CREATE TRIGGER python_environment_verifying_{action.lower()}
            BEFORE {action} ON python_resource_details
            WHEN NEW.phase = 'VERIFYING' AND NOT EXISTS (
                SELECT 1 FROM python_environment_constructions
                WHERE resource_id = NEW.resource_id)
            BEGIN SELECT RAISE(ABORT, 'VERIFYING requires retained environment evidence'); END""")


def downgrade() -> None:
    raise RuntimeError("retained environment evidence requires an explicit forward migration")
