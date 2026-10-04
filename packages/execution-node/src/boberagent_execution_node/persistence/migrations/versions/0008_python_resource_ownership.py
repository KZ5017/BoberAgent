"""Durable Python Resource reservation/ownership only; no runtime can be READY."""

import sqlalchemy as sa
from alembic import op

revision = "0008_python_resource_ownership"
down_revision = "0007_preparation_materialization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "python_resource_details",
        sa.Column(
            "resource_id",
            sa.String(255),
            sa.ForeignKey("runtime_resources.resource_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "preparation_id",
            sa.String(255),
            sa.ForeignKey("preparation_materializations.preparation_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "permit_id",
            sa.String(255),
            sa.ForeignKey("preparation_authorities.permit_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("request_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("baseline_json", sa.JSON(), nullable=False),
        sa.Column("workspace_correlation", sa.String(255), nullable=False, unique=True),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("validity", sa.String(32), nullable=False),
        sa.Column("active_operation_id", sa.String(255)),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("failure_json", sa.JSON()),
        sa.Column("cleanup_state", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "phase IN ('RESERVED','BUILDING','QUARANTINED','REMOVED')", name="ck_python_b_phase"
        ),
        sa.CheckConstraint("validity = 'UNCHECKED'", name="ck_python_b_unchecked"),
        sa.CheckConstraint(
            "cleanup_state IN ('NONE','PENDING','FAILED','COMPLETED')", name="ck_python_cleanup"
        ),
        sa.CheckConstraint("generation >= 0", name="ck_python_generation"),
    )
    op.create_table(
        "python_resource_operations",
        sa.Column("operation_id", sa.String(255), primary_key=True),
        sa.Column(
            "resource_id",
            sa.String(255),
            sa.ForeignKey("python_resource_details.resource_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("owner_token", sa.String(255), nullable=False),
        sa.Column("boot_generation", sa.String(255), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("failure_json", sa.JSON()),
        sa.UniqueConstraint("resource_id", "generation", name="uq_python_operation_generation"),
        sa.CheckConstraint(
            "state IN ('ACTIVE','RELEASED','INTERRUPTED','FAILED','COMPLETED')",
            name="ck_python_operation_state",
        ),
        sa.CheckConstraint(
            "operation IN ('inspect_interpreter','create_empty_environment','verify_environment','revalidate','release')",
            name="ck_python_operation_kind",
        ),
    )
    op.create_table(
        "python_resource_budget_entries",
        sa.Column(
            "operation_id",
            sa.String(255),
            sa.ForeignKey("python_resource_operations.operation_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("category", sa.String(64), primary_key=True),
        sa.Column("reserved", sa.BigInteger(), nullable=False),
        sa.Column("spent", sa.BigInteger()),
        sa.CheckConstraint(
            "reserved >= 0 AND (spent IS NULL OR (spent >= 0 AND spent <= reserved))",
            name="ck_python_budget_amount",
        ),
    )
    # Defense in depth against generic Resource setters. E5-C+ must explicitly migrate
    # this guard before introducing any legitimate readiness path.
    for action in ("INSERT", "UPDATE"):
        op.execute(f"""CREATE TRIGGER python_resource_no_ready_{action.lower()}
            BEFORE {action} ON runtime_resources
            WHEN NEW.resource_type = 'python_runtime' AND NEW.state = 'READY'
            BEGIN SELECT RAISE(ABORT, 'E5-B Python runtime cannot be READY'); END""")
    op.execute("""CREATE TRIGGER python_resource_immutable_binding
        BEFORE UPDATE ON python_resource_details
        WHEN OLD.resource_id != NEW.resource_id OR OLD.preparation_id != NEW.preparation_id
          OR OLD.permit_id != NEW.permit_id OR OLD.request_sha256 != NEW.request_sha256
          OR OLD.request_json != NEW.request_json OR OLD.baseline_json != NEW.baseline_json
          OR OLD.workspace_correlation != NEW.workspace_correlation
        BEGIN SELECT RAISE(ABORT, 'immutable Python Resource reservation'); END""")


def downgrade() -> None:
    op.execute("DROP TRIGGER python_resource_immutable_binding")
    op.execute("DROP TRIGGER python_resource_no_ready_update")
    op.execute("DROP TRIGGER python_resource_no_ready_insert")
    op.drop_table("python_resource_budget_entries")
    op.drop_table("python_resource_operations")
    op.drop_table("python_resource_details")
