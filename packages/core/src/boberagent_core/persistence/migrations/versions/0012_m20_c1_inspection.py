"""Add Core-owned M20-C1 inspection attempts and structural output.

Revision ID: 0012_m20_c1_inspection
Revises: 0011_m20_b3_fixture_mode
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_m20_c1_inspection"
down_revision: str | None = "0011_m20_b3_fixture_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "poc_inspections",
        sa.Column("inspection_id", sa.String(255), primary_key=True),
        sa.Column(
            "mission_id", sa.String(255), sa.ForeignKey("missions.mission_id"), nullable=False
        ),
        sa.Column(
            "hypothesis_id",
            sa.String(255),
            sa.ForeignKey("vulnerability_hypotheses.hypothesis_id"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.String(255),
            sa.ForeignKey("poc_candidates.candidate_id"),
            nullable=False,
        ),
        sa.Column(
            "acquisition_id",
            sa.String(255),
            sa.ForeignKey("poc_acquisitions.acquisition_id"),
            nullable=False,
        ),
        sa.Column(
            "raw_artifact_id",
            sa.String(255),
            sa.ForeignKey("artifacts.artifact_id"),
            nullable=False,
        ),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column("raw_size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "manifest_artifact_id",
            sa.String(255),
            sa.ForeignKey("artifacts.artifact_id"),
            nullable=False,
        ),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("resolved_commit_sha", sa.String(40), nullable=False),
        sa.Column("profile_id", sa.String(128), nullable=False),
        sa.Column("profile_version", sa.String(128), nullable=False),
        sa.Column("config_fingerprint", sa.String(64), nullable=False),
        sa.Column("limits_json", sa.JSON(), nullable=False),
        sa.Column("selected_paths_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("started_at", sa.String(32)),
        sa.Column("finished_at", sa.String(32)),
        sa.Column("document_json", sa.JSON()),
        sa.Column("diagnostic", sa.String(512)),
    )
    op.create_index("ix_poc_inspections_acquisition_id", "poc_inspections", ["acquisition_id"])
    op.create_index("ix_poc_inspections_status", "poc_inspections", ["status"])


def downgrade() -> None:
    op.drop_index("ix_poc_inspections_status", table_name="poc_inspections")
    op.drop_index("ix_poc_inspections_acquisition_id", table_name="poc_inspections")
    op.drop_table("poc_inspections")
