"""Persist transport invocation identity fingerprints.

Revision ID: 0002_invocation_fingerprint
Revises: 0001_runtime_foundation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_invocation_fingerprint"
down_revision: str | None = "0001_runtime_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runtime_runs",
        sa.Column("invocation_fingerprint", sa.String(64)),
    )


def downgrade() -> None:
    op.drop_column("runtime_runs", "invocation_fingerprint")
