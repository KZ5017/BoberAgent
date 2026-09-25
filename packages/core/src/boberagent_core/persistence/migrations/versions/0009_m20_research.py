"""Add bounded Core-owned research history and PoC candidate leads.

Revision ID: 0009_m20_research
Revises: 0008_secret_credentials
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_m20_research"
down_revision: str | None = "0008_secret_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_timestamp = sa.String(length=32)


def upgrade() -> None:
    op.create_table(
        "vulnerability_hypotheses",
        sa.Column("hypothesis_id", sa.String(255), primary_key=True),
        sa.Column(
            "mission_id", sa.String(255), sa.ForeignKey("missions.mission_id"), nullable=False
        ),
        sa.Column("asset_id", sa.String(255), sa.ForeignKey("assets.asset_id"), nullable=False),
        sa.Column("service_id", sa.String(255), sa.ForeignKey("services.service_id")),
        sa.Column("claim", sa.String(512), nullable=False),
        sa.Column("vulnerability_ids_json", sa.JSON(), nullable=False),
        sa.Column("product", sa.String(128)),
        sa.Column("version", sa.String(128)),
        sa.Column("observation_refs_json", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", _timestamp, nullable=False),
    )
    op.create_index("ix_hypotheses_mission_id", "vulnerability_hypotheses", ["mission_id"])
    op.create_table(
        "research_attempts",
        sa.Column("attempt_id", sa.String(255), primary_key=True),
        sa.Column(
            "hypothesis_id",
            sa.String(255),
            sa.ForeignKey("vulnerability_hypotheses.hypothesis_id"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", _timestamp, nullable=False),
        sa.Column("finished_at", _timestamp),
        sa.Column("diagnostic", sa.String(512)),
    )
    op.create_index("ix_research_attempts_hypothesis_id", "research_attempts", ["hypothesis_id"])
    op.create_table(
        "poc_candidates",
        sa.Column("candidate_id", sa.String(255), primary_key=True),
        sa.Column(
            "mission_id", sa.String(255), sa.ForeignKey("missions.mission_id"), nullable=False
        ),
        sa.Column(
            "hypothesis_id",
            sa.String(255),
            sa.ForeignKey("vulnerability_hypotheses.hypothesis_id"),
            nullable=False,
        ),
        sa.Column("source_identity", sa.String(2048), nullable=False),
        sa.Column("source_class", sa.String(32), nullable=False),
        sa.Column("source_uri", sa.String(2048), nullable=False),
        sa.Column("first_seen_at", _timestamp, nullable=False),
        sa.Column("last_seen_at", _timestamp, nullable=False),
        sa.UniqueConstraint("hypothesis_id", "source_identity", name="uq_poc_candidate_source"),
    )
    op.create_index("ix_poc_candidates_hypothesis_id", "poc_candidates", ["hypothesis_id"])
    op.create_table(
        "research_source_hits",
        sa.Column("hit_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "attempt_id",
            sa.String(255),
            sa.ForeignKey("research_attempts.attempt_id"),
            nullable=False,
        ),
        sa.Column("candidate_id", sa.String(255), sa.ForeignKey("poc_candidates.candidate_id")),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("source_json", sa.JSON(), nullable=False),
        sa.Column("source_identity", sa.String(2048)),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("decision_reason", sa.String(255)),
        sa.Column("observed_at", _timestamp, nullable=False),
    )
    op.create_index("ix_research_source_hits_attempt_id", "research_source_hits", ["attempt_id"])
    op.create_index(
        "ix_research_source_hits_candidate_id", "research_source_hits", ["candidate_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_research_source_hits_candidate_id", table_name="research_source_hits")
    op.drop_index("ix_research_source_hits_attempt_id", table_name="research_source_hits")
    op.drop_table("research_source_hits")
    op.drop_index("ix_poc_candidates_hypothesis_id", table_name="poc_candidates")
    op.drop_table("poc_candidates")
    op.drop_index("ix_research_attempts_hypothesis_id", table_name="research_attempts")
    op.drop_table("research_attempts")
    op.drop_index("ix_hypotheses_mission_id", table_name="vulnerability_hypotheses")
    op.drop_table("vulnerability_hypotheses")
