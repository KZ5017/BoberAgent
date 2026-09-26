"""Add Core-owned M20-B acquisition decisions and immutable source correlation.

Revision ID: 0010_m20_acquisition
Revises: 0009_m20_research
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_m20_acquisition"
down_revision: str | None = "0009_m20_research"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_timestamp = sa.String(length=32)


def upgrade() -> None:
    op.create_table(
        "poc_acquisitions",
        sa.Column("acquisition_id", sa.String(255), primary_key=True),
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
            "selected_hit_id",
            sa.Integer(),
            sa.ForeignKey("research_source_hits.hit_id"),
            nullable=False,
        ),
        sa.Column(
            "research_attempt_id",
            sa.String(255),
            sa.ForeignKey("research_attempts.attempt_id"),
            nullable=False,
        ),
        sa.Column("research_provider_id", sa.String(128), nullable=False),
        sa.Column("source_identity", sa.String(2048), nullable=False),
        sa.Column("source_uri", sa.String(2048), nullable=False),
        sa.Column("repository_uri", sa.String(255), nullable=False),
        sa.Column("provider_repository_id", sa.Integer(), nullable=False),
        sa.Column("historical_ref", sa.String(247), nullable=False),
        sa.Column("bounds_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("run_id", sa.String(255), sa.ForeignKey("capability_runs.run_id"), unique=True),
        sa.Column(
            "routing_provider_id",
            sa.String(36),
            sa.ForeignKey("capability_providers.provider_id"),
        ),
        sa.Column("node_id", sa.String(255)),
        sa.Column("receipt_json", sa.JSON()),
        sa.Column("resolved_commit_sha", sa.String(40)),
        sa.Column("raw_artifact_id", sa.String(255), sa.ForeignKey("artifacts.artifact_id")),
        sa.Column("raw_archive_sha256", sa.String(64)),
        sa.Column("raw_archive_size_bytes", sa.Integer()),
        sa.Column("manifest_artifact_id", sa.String(255), sa.ForeignKey("artifacts.artifact_id")),
        sa.Column("manifest_sha256", sa.String(64)),
        sa.Column("adapter_id", sa.String(128)),
        sa.Column("adapter_version", sa.String(128)),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("updated_at", _timestamp, nullable=False),
        sa.Column("diagnostic", sa.String(512)),
    )
    op.create_index("ix_poc_acquisitions_candidate_id", "poc_acquisitions", ["candidate_id"])
    op.create_index("ix_poc_acquisitions_status", "poc_acquisitions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_poc_acquisitions_status", table_name="poc_acquisitions")
    op.drop_index("ix_poc_acquisitions_candidate_id", table_name="poc_acquisitions")
    op.drop_table("poc_acquisitions")
