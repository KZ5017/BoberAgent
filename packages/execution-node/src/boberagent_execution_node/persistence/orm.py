"""Private ORM rows for the node-local runtime database."""

from datetime import datetime

from boberagent_contracts import JsonObject
from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .types import UTCDateTime


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runtime_runs"

    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(255), nullable=False)
    capability_id: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_run_id: Mapped[str | None] = mapped_column(String(255))
    workflow_run_id: Mapped[str | None] = mapped_column(String(255))
    invocation_fingerprint: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error_code: Mapped[str | None] = mapped_column(String(255))


class ProcessRow(Base):
    __tablename__ = "managed_processes"
    __table_args__: tuple[Index] = (Index("ix_managed_processes_run_id", "run_id"),)

    process_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    tool: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    argument_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pid: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    exit_code: Mapped[int | None] = mapped_column(Integer)


class WorkspaceRow(Base):
    __tablename__ = "workspaces"
    __table_args__: tuple[Index] = (Index("ix_workspaces_owner_ref", "owner_ref"),)

    workspace_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    owner_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(255), nullable=False)
    isolation: Mapped[str] = mapped_column(String(32), nullable=False)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ArtifactRow(Base):
    __tablename__ = "artifact_spool"
    __table_args__: tuple[Index] = (Index("ix_artifact_spool_run_id", "run_id"),)

    artifact_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    artifact_type: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    sync_state: Mapped[str] = mapped_column(String(32), nullable=False)
    sync_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sync_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sync_error: Mapped[str | None] = mapped_column(Text)


class EventOutboxRow(Base):
    __tablename__ = "event_outbox"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    event_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    delivery_state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ResultOutboxRow(Base):
    __tablename__ = "result_outbox"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_runs.run_id", ondelete="CASCADE"), unique=True, nullable=False
    )
    result_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    delivery_state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class RuntimeResourceRow(Base):
    __tablename__ = "runtime_resources"
    __table_args__: tuple[Index] = (Index("ix_runtime_resources_owner_ref", "owner_ref"),)

    resource_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_run: Mapped[str] = mapped_column(
        ForeignKey("runtime_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    access_modes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    lifecycle_metadata_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)


class RuntimeSessionRow(Base):
    __tablename__ = "runtime_sessions"
    __table_args__: tuple[Index, Index] = (
        Index("ix_runtime_sessions_owner_ref", "owner_ref"),
        Index("ix_runtime_sessions_target_ref", "target_ref"),
    )

    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    session_type: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_run: Mapped[str] = mapped_column(
        ForeignKey("runtime_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    target_ref: Mapped[str | None] = mapped_column(String(255))
    identity_ref: Mapped[str | None] = mapped_column(String(255))
    access_context_ref: Mapped[str | None] = mapped_column(String(255))
    resource_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    supported_operations_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    access_modes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    lifecycle_metadata_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)


class RuntimeInteractionRow(Base):
    __tablename__ = "runtime_interactions"
    __table_args__: tuple[Index, Index] = (
        Index("ix_runtime_interactions_run_id", "run_id"),
        Index("ix_runtime_interactions_state", "state"),
    )

    interaction_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    mission_id: Mapped[str] = mapped_column(String(255), nullable=False)
    workflow_run_id: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    request_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    response_json: Mapped[JsonObject | None] = mapped_column(JSON)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
