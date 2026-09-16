"""Create the Milestone 2 Core persistence schema.

Revision ID: 0001_core_persistence
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_core_persistence"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_timestamp = sa.String(length=32)


def upgrade() -> None:
    op.create_table(
        "missions",
        sa.Column("mission_id", sa.String(length=255), primary_key=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("name", sa.String(length=255)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "assets",
        sa.Column("asset_id", sa.String(length=255), primary_key=True),
        sa.Column(
            "mission_id",
            sa.String(length=255),
            sa.ForeignKey("missions.mission_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("primary_address", sa.String(length=255), nullable=False),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_assets_mission_id", "assets", ["mission_id"])
    op.create_table(
        "workflow_runs",
        sa.Column("workflow_run_id", sa.String(length=255), primary_key=True),
        sa.Column(
            "mission_id",
            sa.String(length=255),
            sa.ForeignKey("missions.mission_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("procedure_ref", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("updated_at", _timestamp, nullable=False),
    )
    op.create_index("ix_workflow_runs_mission_id", "workflow_runs", ["mission_id"])
    op.create_table(
        "goals",
        sa.Column("goal_id", sa.String(length=255), primary_key=True),
        sa.Column(
            "mission_id",
            sa.String(length=255),
            sa.ForeignKey("missions.mission_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workflow_run_id",
            sa.String(length=255),
            sa.ForeignKey("workflow_runs.workflow_run_id", ondelete="CASCADE"),
        ),
        sa.Column("goal_type", sa.String(length=255), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("updated_at", _timestamp, nullable=False),
    )
    op.create_index("ix_goals_mission_id", "goals", ["mission_id"])
    op.create_index("ix_goals_workflow_run_id", "goals", ["workflow_run_id"])
    op.create_table(
        "capability_runs",
        sa.Column("run_id", sa.String(length=255), primary_key=True),
        sa.Column(
            "mission_id",
            sa.String(length=255),
            sa.ForeignKey("missions.mission_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capability_id", sa.String(length=255), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("started_at", _timestamp),
        sa.Column("finished_at", _timestamp),
        sa.Column(
            "parent_run_id",
            sa.String(length=255),
            sa.ForeignKey("capability_runs.run_id", ondelete="SET NULL"),
        ),
        sa.Column(
            "workflow_run_id",
            sa.String(length=255),
            sa.ForeignKey("workflow_runs.workflow_run_id", ondelete="SET NULL"),
        ),
    )
    op.create_index("ix_capability_runs_mission_id", "capability_runs", ["mission_id"])
    op.create_table(
        "artifacts",
        sa.Column("artifact_id", sa.String(length=255), primary_key=True),
        sa.Column("artifact_type", sa.String(length=255), nullable=False),
        sa.Column("storage_ref", sa.String(length=255), nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=255),
            sa.ForeignKey("capability_runs.run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("sha256", sa.String(length=64)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("media_type", sa.String(length=255)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])
    op.create_table(
        "observations",
        sa.Column("observation_id", sa.String(length=255), primary_key=True),
        sa.Column("observation_type", sa.String(length=255), nullable=False),
        sa.Column("subject_ref", sa.String(length=255)),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("observed_at", _timestamp, nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=255),
            sa.ForeignKey("capability_runs.run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("materialization_status", sa.String(length=32), nullable=False),
        sa.Column("materialization_error", sa.Text()),
    )
    op.create_index("ix_observations_run_id", "observations", ["run_id"])
    op.create_index("ix_observations_type", "observations", ["observation_type"])
    op.create_index(
        "ix_observations_materialization_status",
        "observations",
        ["materialization_status"],
    )
    op.create_table(
        "services",
        sa.Column("service_id", sa.String(length=255), primary_key=True),
        sa.Column(
            "asset_id",
            sa.String(length=255),
            sa.ForeignKey("assets.asset_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("transport", sa.String(length=32), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("service", sa.String(length=255)),
        sa.Column("product", sa.String(length=255)),
        sa.Column("version", sa.String(length=255)),
        sa.Column("first_observed_at", _timestamp, nullable=False),
        sa.Column("last_observed_at", _timestamp, nullable=False),
        sa.Column(
            "current_observation_id",
            sa.String(length=255),
            sa.ForeignKey("observations.observation_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provenance_refs_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("asset_id", "transport", "port", name="uq_services_endpoint"),
    )
    op.create_index("ix_services_asset_id", "services", ["asset_id"])


def downgrade() -> None:
    op.drop_index("ix_services_asset_id", table_name="services")
    op.drop_table("services")
    op.drop_index("ix_observations_materialization_status", table_name="observations")
    op.drop_index("ix_observations_type", table_name="observations")
    op.drop_index("ix_observations_run_id", table_name="observations")
    op.drop_table("observations")
    op.drop_index("ix_artifacts_run_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_capability_runs_mission_id", table_name="capability_runs")
    op.drop_table("capability_runs")
    op.drop_index("ix_goals_workflow_run_id", table_name="goals")
    op.drop_index("ix_goals_mission_id", table_name="goals")
    op.drop_table("goals")
    op.drop_index("ix_workflow_runs_mission_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index("ix_assets_mission_id", table_name="assets")
    op.drop_table("assets")
    op.drop_table("missions")
