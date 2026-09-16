"""Private SQLAlchemy ORM mappings for the Core database."""

from __future__ import annotations

from datetime import datetime

from boberagent_contracts import JsonObject, JsonValue
from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .types import UTCDateTime


class Base(DeclarativeBase):
    """Private declarative base used by migrations and repositories."""


class MissionRow(Base):
    __tablename__ = "missions"

    mission_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False, default=dict)


class AssetRow(Base):
    __tablename__ = "assets"
    __table_args__: tuple[Index] = (Index("ix_assets_mission_id", "mission_id"),)

    asset_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_address: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    metadata_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False, default=dict)


class WorkflowRunRow(Base):
    __tablename__ = "workflow_runs"
    __table_args__: tuple[Index] = (Index("ix_workflow_runs_mission_id", "mission_id"),)

    workflow_run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False
    )
    procedure_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class GoalRow(Base):
    __tablename__ = "goals"
    __table_args__: tuple[Index, Index] = (
        Index("ix_goals_mission_id", "mission_id"),
        Index("ix_goals_workflow_run_id", "workflow_run_id"),
    )

    goal_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_runs.workflow_run_id", ondelete="CASCADE")
    )
    goal_type: Mapped[str] = mapped_column(String(255), nullable=False)
    parameters_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class CapabilityRunRow(Base):
    __tablename__ = "capability_runs"
    __table_args__: tuple[Index] = (Index("ix_capability_runs_mission_id", "mission_id"),)

    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False
    )
    capability_id: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    parent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("capability_runs.run_id", ondelete="SET NULL")
    )
    workflow_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_runs.workflow_run_id", ondelete="SET NULL")
    )


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    __table_args__: tuple[Index] = (Index("ix_artifacts_run_id", "run_id"),)

    artifact_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    artifact_type: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("capability_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    media_type: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False, default=dict)


class ObservationRow(Base):
    __tablename__ = "observations"
    __table_args__: tuple[Index, Index, Index] = (
        Index("ix_observations_run_id", "run_id"),
        Index("ix_observations_type", "observation_type"),
        Index("ix_observations_materialization_status", "materialization_status"),
    )

    observation_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    observation_type: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_ref: Mapped[str | None] = mapped_column(String(255))
    value_json: Mapped[JsonValue] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("capability_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    evidence_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    materialization_status: Mapped[str] = mapped_column(String(32), nullable=False)
    materialization_error: Mapped[str | None] = mapped_column(Text)


class ServiceRow(Base):
    __tablename__ = "services"
    __table_args__: tuple[UniqueConstraint, Index] = (
        UniqueConstraint("asset_id", "transport", "port", name="uq_services_endpoint"),
        Index("ix_services_asset_id", "asset_id"),
    )

    service_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.asset_id", ondelete="CASCADE"), nullable=False
    )
    transport: Mapped[str] = mapped_column(String(32), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    service: Mapped[str | None] = mapped_column(String(255))
    product: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(255))
    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    current_observation_id: Mapped[str] = mapped_column(
        ForeignKey("observations.observation_id", ondelete="RESTRICT"), nullable=False
    )
    provenance_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
