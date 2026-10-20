"""Retain exact E6 completion context and final evidence on the existing attempt."""

import sqlalchemy as sa
from alembic import op

revision = "0018_m20_e6_completion"
down_revision = "0017_m20_e3_import_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("completion_context_json", "receipt_json", "final_manifest_json"):
        op.add_column("runtime_preparation_attempts", sa.Column(name, sa.JSON()))
    op.add_column(
        "runtime_preparation_attempts", sa.Column("completion_error_code", sa.String(128))
    )


def downgrade() -> None:
    for name in (
        "completion_error_code",
        "final_manifest_json",
        "receipt_json",
        "completion_context_json",
    ):
        op.drop_column("runtime_preparation_attempts", name)
