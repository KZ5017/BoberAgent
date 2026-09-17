"""Add Core Artifact content availability and transfer metadata.

Revision ID: 0003_artifact_content
Revises: 0002_transport_inbox
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql.schema import SchemaItem

revision: str = "0003_artifact_content"
down_revision: str | None = "0002_transport_inbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_timestamp = sa.String(length=32)


def upgrade() -> None:
    _create_artifact_table("artifacts_m6", include_content=True, run_foreign_key=False)
    op.execute(
        sa.text(
            """
            INSERT INTO artifacts_m6 (
                artifact_id, artifact_type, storage_ref, run_id, created_at, sha256,
                size_bytes, media_type, metadata_json, content_state, received_bytes
            )
            SELECT artifact_id, artifact_type, storage_ref, run_id, created_at, sha256,
                   size_bytes, media_type, metadata_json, 'METADATA_ONLY', 0
            FROM artifacts
            """
        )
    )
    op.drop_index("ix_artifacts_run_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.rename_table("artifacts_m6", "artifacts")
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])
    op.create_index("ix_artifacts_sha256", "artifacts", ["sha256"])


def downgrade() -> None:
    _create_artifact_table("artifacts_m5", include_content=False, run_foreign_key=True)
    op.execute(
        sa.text(
            """
            INSERT INTO artifacts_m5 (
                artifact_id, artifact_type, storage_ref, run_id, created_at, sha256,
                size_bytes, media_type, metadata_json
            )
            SELECT artifact_id, artifact_type, storage_ref, run_id, created_at, sha256,
                   size_bytes, media_type, metadata_json
            FROM artifacts
            """
        )
    )
    op.drop_index("ix_artifacts_sha256", table_name="artifacts")
    op.drop_index("ix_artifacts_run_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.rename_table("artifacts_m5", "artifacts")
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])


def _create_artifact_table(
    name: str,
    *,
    include_content: bool,
    run_foreign_key: bool,
) -> None:
    run_type = sa.String(length=255)
    run_column = (
        sa.Column(
            "run_id",
            run_type,
            sa.ForeignKey("capability_runs.run_id", ondelete="RESTRICT"),
            nullable=False,
        )
        if run_foreign_key
        else sa.Column("run_id", run_type, nullable=False)
    )
    columns: list[SchemaItem] = [
        sa.Column("artifact_id", sa.String(length=255), primary_key=True),
        sa.Column("artifact_type", sa.String(length=255), nullable=False),
        sa.Column("storage_ref", sa.String(length=255), nullable=False),
        run_column,
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("sha256", sa.String(length=64)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("media_type", sa.String(length=255)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    ]
    if include_content:
        columns.extend(
            [
                sa.Column("content_state", sa.String(length=32), nullable=False),
                sa.Column("content_key", sa.String(length=255)),
                sa.Column("source_node_id", sa.String(length=255)),
                sa.Column("transfer_id", sa.String(length=255)),
                sa.Column("received_bytes", sa.Integer(), nullable=False),
                sa.Column("sync_error", sa.Text()),
            ]
        )
    op.create_table(name, *columns)
