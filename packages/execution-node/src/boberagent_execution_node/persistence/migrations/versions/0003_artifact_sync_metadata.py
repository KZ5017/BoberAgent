"""Persist Artifact synchronization retry metadata.

Revision ID: 0003_artifact_sync_metadata
Revises: 0002_invocation_fingerprint
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_artifact_sync_metadata"
down_revision: str | None = "0002_invocation_fingerprint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_timestamp = sa.String(length=32)


def upgrade() -> None:
    op.add_column(
        "artifact_spool",
        sa.Column("sync_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("artifact_spool", sa.Column("last_sync_attempt_at", _timestamp))
    op.add_column("artifact_spool", sa.Column("sync_error", sa.Text()))


def downgrade() -> None:
    op.drop_column("artifact_spool", "sync_error")
    op.drop_column("artifact_spool", "last_sync_attempt_at")
    op.drop_column("artifact_spool", "sync_attempt_count")
