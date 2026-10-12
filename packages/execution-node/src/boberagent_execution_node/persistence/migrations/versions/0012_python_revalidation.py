"""E5-F append-only proof and guarded current availability; no E6 completion."""

import sqlalchemy as sa
from alembic import op

revision = "0012_python_revalidation"
down_revision = "0011_empty_python_environment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TRIGGER python_resource_immutable_binding")
    with op.batch_alter_table("python_resource_details") as batch:
        batch.drop_constraint("ck_python_e_phase", type_="check")
        batch.drop_constraint("ck_python_b_unchecked", type_="check")
        batch.create_check_constraint(
            "ck_python_f_phase",
            "phase IN ('RESERVED','BUILDING','VERIFYING','PUBLISHED','QUARANTINED','REMOVED')",
        )
        batch.create_check_constraint(
            "ck_python_f_validity", "validity IN ('UNCHECKED','VALID','INVALID')"
        )
        batch.add_column(sa.Column("checked_at", sa.String(40), nullable=True))
        batch.add_column(sa.Column("checked_boot", sa.String(255), nullable=True))
        batch.add_column(sa.Column("verification_id", sa.String(255), nullable=True))
        batch.create_check_constraint(
            "ck_python_f_current",
            "(validity = 'UNCHECKED' AND checked_at IS NULL AND checked_boot IS NULL) OR "
            "(validity != 'UNCHECKED' AND checked_at IS NOT NULL AND checked_boot IS NOT NULL)",
        )
    op.execute("""CREATE TRIGGER python_resource_immutable_binding
        BEFORE UPDATE ON python_resource_details
        WHEN OLD.resource_id != NEW.resource_id OR OLD.preparation_id != NEW.preparation_id
          OR OLD.permit_id != NEW.permit_id OR OLD.request_sha256 != NEW.request_sha256
          OR OLD.request_json != NEW.request_json OR OLD.baseline_json != NEW.baseline_json
          OR OLD.workspace_correlation != NEW.workspace_correlation
        BEGIN SELECT RAISE(ABORT, 'immutable Python Resource reservation'); END""")
    for action in ("INSERT", "UPDATE"):
        op.execute(f"""CREATE TRIGGER python_environment_verifying_{action.lower()}
            BEFORE {action} ON python_resource_details
            WHEN NEW.phase = 'VERIFYING' AND NOT EXISTS (
                SELECT 1 FROM python_environment_constructions
                WHERE resource_id = NEW.resource_id)
            BEGIN SELECT RAISE(ABORT, 'VERIFYING requires retained environment evidence'); END""")
    op.create_table(
        "python_runtime_revalidations",
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
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("proof_json", sa.JSON(), nullable=False),
    )
    for action in ("UPDATE", "DELETE"):
        op.execute(f"""CREATE TRIGGER python_revalidation_no_{action.lower()}
            BEFORE {action} ON python_runtime_revalidations
            BEGIN SELECT RAISE(ABORT, 'revalidation history is immutable'); END""")
    for action in ("INSERT", "UPDATE"):
        op.execute(f"DROP TRIGGER python_resource_no_ready_{action.lower()}")
        op.execute(f"""CREATE TRIGGER python_resource_no_ready_{action.lower()}
            BEFORE {action} ON runtime_resources
            WHEN NEW.resource_type = 'python_runtime' AND NEW.state = 'READY'
              AND NOT EXISTS (SELECT 1 FROM python_resource_details d
                JOIN python_runtime_revalidations v ON v.operation_id = d.verification_id
                JOIN python_environment_constructions e ON e.resource_id = d.resource_id
                WHERE d.resource_id = NEW.resource_id AND v.resource_id = d.resource_id
                  AND d.phase = 'PUBLISHED' AND d.validity = 'VALID')
            BEGIN SELECT RAISE(ABORT, 'READY requires fresh runtime proof'); END""")
    for action in ("INSERT", "UPDATE"):
        op.execute(f"""CREATE TRIGGER python_runtime_valid_{action.lower()}
            BEFORE {action} ON python_resource_details
            WHEN NEW.validity = 'VALID' AND (NEW.phase != 'PUBLISHED' OR NOT EXISTS (
                SELECT 1 FROM python_runtime_revalidations v
                JOIN python_resource_operations o ON o.operation_id = v.operation_id
                WHERE v.operation_id = NEW.verification_id AND v.resource_id = NEW.resource_id
                  AND o.state = 'COMPLETED' AND o.boot_generation = NEW.checked_boot))
            BEGIN SELECT RAISE(ABORT, 'VALID requires completed current-boot proof'); END""")


def downgrade() -> None:
    raise RuntimeError("runtime verification history requires a forward migration")
