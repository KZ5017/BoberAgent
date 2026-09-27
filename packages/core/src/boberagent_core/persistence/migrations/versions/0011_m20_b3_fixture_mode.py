"""Persist explicit loopback-fixture acquisition mode without rewriting B1 history.

Revision ID: 0011_m20_b3_fixture_mode
Revises: 0010_m20_acquisition
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_m20_b3_fixture_mode"
down_revision: str | None = "0010_m20_acquisition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("poc_acquisitions") as batch:
        batch.add_column(
            sa.Column(
                "source_kind",
                sa.String(length=32),
                nullable=False,
                server_default="github_repository",
            )
        )
        batch.add_column(sa.Column("fixture_port", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("poc_acquisitions") as batch:
        batch.drop_column("fixture_port")
        batch.drop_column("source_kind")
