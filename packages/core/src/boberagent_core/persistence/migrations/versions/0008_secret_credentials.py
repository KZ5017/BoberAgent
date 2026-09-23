"""Add canonical Secrets, Credentials, access audit metadata and Core Events.

Revision ID: 0008_secret_credentials
Revises: 0007_durable_interactions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_secret_credentials"
down_revision: str | None = "0007_durable_interactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_timestamp = sa.String(length=32)


def upgrade() -> None:
    op.add_column(
        "workflow_step_runs",
        sa.Column(
            "credential_refs_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "workflow_step_runs",
        sa.Column(
            "secret_refs_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.create_table(
        "secrets",
        sa.Column("secret_id", sa.String(255), primary_key=True),
        sa.Column(
            "mission_id",
            sa.String(255),
            sa.ForeignKey("missions.mission_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("secret_type", sa.String(64), nullable=False),
        sa.Column("value_blob", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column(
            "created_by_run_id",
            sa.String(255),
            sa.ForeignKey("capability_runs.run_id", ondelete="SET NULL"),
        ),
        sa.Column(
            "source_observation_id",
            sa.String(255),
            sa.ForeignKey("observations.observation_id", ondelete="SET NULL"),
        ),
        sa.Column("source_artifact_refs_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_secrets_mission_id", "secrets", ["mission_id"])
    op.create_index("ix_secrets_status", "secrets", ["status"])

    op.create_table(
        "credentials",
        sa.Column("credential_id", sa.String(255), primary_key=True),
        sa.Column(
            "mission_id",
            sa.String(255),
            sa.ForeignKey("missions.mission_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("credential_type", sa.String(64), nullable=False),
        sa.Column("username", sa.String(255)),
        sa.Column("identity_ref", sa.String(255)),
        sa.Column("secret_bindings_json", sa.JSON(), nullable=False),
        sa.Column("scope_refs_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_observation_refs_json", sa.JSON(), nullable=False),
        sa.Column("source_artifact_refs_json", sa.JSON(), nullable=False),
        sa.Column("created_at", _timestamp, nullable=False),
        sa.Column("updated_at", _timestamp, nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_credentials_mission_id", "credentials", ["mission_id"])
    op.create_index("ix_credentials_status", "credentials", ["status"])

    op.create_table(
        "core_events",
        sa.Column("event_id", sa.String(255), primary_key=True),
        sa.Column("event_type", sa.String(255), nullable=False),
        sa.Column("timestamp", _timestamp, nullable=False),
        sa.Column(
            "mission_id",
            sa.String(255),
            sa.ForeignKey("missions.mission_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_ref", sa.String(255), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_core_events_mission_id", "core_events", ["mission_id"])
    op.create_index("ix_core_events_type", "core_events", ["event_type"])

    op.create_table(
        "secret_access_records",
        sa.Column("access_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "secret_id",
            sa.String(255),
            sa.ForeignKey("secrets.secret_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mission_id",
            sa.String(255),
            sa.ForeignKey("missions.mission_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(255),
            sa.ForeignKey("capability_runs.run_id", ondelete="SET NULL"),
        ),
        sa.Column("accessor", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(255), nullable=False),
        sa.Column("accessed_at", _timestamp, nullable=False),
    )
    op.create_index("ix_secret_access_secret_id", "secret_access_records", ["secret_id"])
    op.create_index("ix_secret_access_run_id", "secret_access_records", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_secret_access_run_id", table_name="secret_access_records")
    op.drop_index("ix_secret_access_secret_id", table_name="secret_access_records")
    op.drop_table("secret_access_records")
    op.drop_index("ix_core_events_type", table_name="core_events")
    op.drop_index("ix_core_events_mission_id", table_name="core_events")
    op.drop_table("core_events")
    op.drop_index("ix_credentials_status", table_name="credentials")
    op.drop_index("ix_credentials_mission_id", table_name="credentials")
    op.drop_table("credentials")
    op.drop_index("ix_secrets_status", table_name="secrets")
    op.drop_index("ix_secrets_mission_id", table_name="secrets")
    op.drop_table("secrets")
    op.drop_column("workflow_step_runs", "secret_refs_json")
    op.drop_column("workflow_step_runs", "credential_refs_json")
