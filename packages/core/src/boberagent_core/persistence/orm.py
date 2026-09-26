"""Private SQLAlchemy ORM mappings for the Core database."""

from __future__ import annotations

from datetime import datetime

from boberagent_contracts import JsonObject, JsonValue
from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
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
    definition_json: Mapped[JsonObject | None] = mapped_column(JSON)
    failure_reason: Mapped[str | None] = mapped_column(Text)


class WorkflowStepRunRow(Base):
    __tablename__ = "workflow_step_runs"
    __table_args__: tuple[UniqueConstraint, Index, Index] = (
        UniqueConstraint("workflow_run_id", "position", name="uq_workflow_step_position"),
        Index("ix_workflow_step_runs_status", "status"),
        Index("ix_workflow_step_runs_capability_run_id", "capability_run_id"),
    )

    workflow_run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.workflow_run_id", ondelete="CASCADE"), primary_key=True
    )
    step_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    capability_id: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    inputs_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False, default=dict)
    credential_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    secret_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    success_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    capability_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("capability_runs.run_id", ondelete="RESTRICT"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_reason: Mapped[str | None] = mapped_column(Text)


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
    __table_args__: tuple[Index, Index] = (
        Index("ix_artifacts_run_id", "run_id"),
        Index("ix_artifacts_sha256", "sha256"),
    )

    artifact_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    artifact_type: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    media_type: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False, default=dict)
    content_state: Mapped[str] = mapped_column(String(32), nullable=False, default="METADATA_ONLY")
    content_key: Mapped[str | None] = mapped_column(String(255))
    source_node_id: Mapped[str | None] = mapped_column(String(255))
    transfer_id: Mapped[str | None] = mapped_column(String(255))
    received_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sync_error: Mapped[str | None] = mapped_column(Text)


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


class SecretRow(Base):
    __tablename__ = "secrets"
    __table_args__: tuple[Index, Index] = (
        Index("ix_secrets_mission_id", "mission_id"),
        Index("ix_secrets_status", "status"),
    )

    secret_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False
    )
    secret_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_by_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("capability_runs.run_id", ondelete="SET NULL")
    )
    source_observation_id: Mapped[str | None] = mapped_column(
        ForeignKey("observations.observation_id", ondelete="SET NULL")
    )
    source_artifact_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False, default=dict)


class CredentialRow(Base):
    __tablename__ = "credentials"
    __table_args__: tuple[Index, Index] = (
        Index("ix_credentials_mission_id", "mission_id"),
        Index("ix_credentials_status", "status"),
    )

    credential_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False
    )
    credential_type: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    identity_ref: Mapped[str | None] = mapped_column(String(255))
    secret_bindings_json: Mapped[list[JsonObject]] = mapped_column(JSON, nullable=False)
    scope_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_observation_refs_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    source_artifact_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    metadata_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False, default=dict)


class CoreEventRow(Base):
    __tablename__ = "core_events"
    __table_args__: tuple[Index, Index] = (
        Index("ix_core_events_mission_id", "mission_id"),
        Index("ix_core_events_type", "event_type"),
    )

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False
    )
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)


class SecretAccessRow(Base):
    __tablename__ = "secret_access_records"
    __table_args__: tuple[Index, Index] = (
        Index("ix_secret_access_secret_id", "secret_id"),
        Index("ix_secret_access_run_id", "run_id"),
    )

    access_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    secret_id: Mapped[str] = mapped_column(
        ForeignKey("secrets.secret_id", ondelete="CASCADE"), nullable=False
    )
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.mission_id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("capability_runs.run_id", ondelete="SET NULL")
    )
    accessor: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(255), nullable=False)
    accessed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


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


class VulnerabilityHypothesisRow(Base):
    __tablename__ = "vulnerability_hypotheses"
    __table_args__: tuple[Index] = (Index("ix_hypotheses_mission_id", "mission_id"),)

    hypothesis_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.mission_id"), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.asset_id"), nullable=False)
    service_id: Mapped[str | None] = mapped_column(ForeignKey("services.service_id"))
    claim: Mapped[str] = mapped_column(String(512), nullable=False)
    vulnerability_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    product: Mapped[str | None] = mapped_column(String(128))
    version: Mapped[str | None] = mapped_column(String(128))
    observation_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    provenance: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ResearchAttemptRow(Base):
    __tablename__ = "research_attempts"
    __table_args__: tuple[Index] = (Index("ix_research_attempts_hypothesis_id", "hypothesis_id"),)

    attempt_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("vulnerability_hypotheses.hypothesis_id"), nullable=False
    )
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    diagnostic: Mapped[str | None] = mapped_column(String(512))


class PoCCandidateRow(Base):
    __tablename__ = "poc_candidates"
    __table_args__: tuple[UniqueConstraint, Index] = (
        UniqueConstraint("hypothesis_id", "source_identity", name="uq_poc_candidate_source"),
        Index("ix_poc_candidates_hypothesis_id", "hypothesis_id"),
    )

    candidate_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.mission_id"), nullable=False)
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("vulnerability_hypotheses.hypothesis_id"), nullable=False
    )
    source_identity: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_class: Mapped[str] = mapped_column(String(32), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ResearchSourceHitRow(Base):
    __tablename__ = "research_source_hits"
    __table_args__: tuple[Index, Index] = (
        Index("ix_research_source_hits_attempt_id", "attempt_id"),
        Index("ix_research_source_hits_candidate_id", "candidate_id"),
    )

    hit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("research_attempts.attempt_id"), nullable=False
    )
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("poc_candidates.candidate_id"))
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    source_identity: Mapped[str | None] = mapped_column(String(2048))
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(String(255))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class PoCAcquisitionRow(Base):
    __tablename__ = "poc_acquisitions"
    __table_args__: tuple[Index, Index] = (
        Index("ix_poc_acquisitions_candidate_id", "candidate_id"),
        Index("ix_poc_acquisitions_status", "status"),
    )

    acquisition_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.mission_id"), nullable=False)
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("vulnerability_hypotheses.hypothesis_id"), nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("poc_candidates.candidate_id"), nullable=False
    )
    selected_hit_id: Mapped[int] = mapped_column(
        ForeignKey("research_source_hits.hit_id"), nullable=False
    )
    research_attempt_id: Mapped[str] = mapped_column(
        ForeignKey("research_attempts.attempt_id"), nullable=False
    )
    research_provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_identity: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    repository_uri: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_repository_id: Mapped[int] = mapped_column(Integer, nullable=False)
    historical_ref: Mapped[str] = mapped_column(String(247), nullable=False)
    bounds_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("capability_runs.run_id"), unique=True)
    routing_provider_id: Mapped[str | None] = mapped_column(
        ForeignKey("capability_providers.provider_id")
    )
    node_id: Mapped[str | None] = mapped_column(String(255))
    receipt_json: Mapped[JsonObject | None] = mapped_column(JSON)
    resolved_commit_sha: Mapped[str | None] = mapped_column(String(40))
    raw_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.artifact_id"))
    raw_archive_sha256: Mapped[str | None] = mapped_column(String(64))
    raw_archive_size_bytes: Mapped[int | None] = mapped_column(Integer)
    manifest_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.artifact_id"))
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    adapter_id: Mapped[str | None] = mapped_column(String(128))
    adapter_version: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    diagnostic: Mapped[str | None] = mapped_column(String(512))


class TransportInboxRow(Base):
    __tablename__ = "transport_inbox"
    __table_args__: tuple[Index, Index] = (
        Index("ix_transport_inbox_correlation_id", "correlation_id"),
        Index("ix_transport_inbox_kind", "message_kind"),
    )

    message_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    message_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_id: Mapped[str] = mapped_column(String(255), nullable=False)
    outbox_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    envelope_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    delivery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class InteractionRow(Base):
    __tablename__ = "interactions"
    __table_args__: tuple[Index, Index, Index] = (
        Index("ix_interactions_state", "state"),
        Index("ix_interactions_run_id", "run_id"),
        Index("ix_interactions_mission_id", "mission_id"),
    )

    interaction_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    mission_id: Mapped[str] = mapped_column(String(255), nullable=False)
    workflow_run_id: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    request_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    response_json: Mapped[JsonObject | None] = mapped_column(JSON)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancellation_reason: Mapped[str | None] = mapped_column(Text)


class CapabilityProviderRow(Base):
    __tablename__ = "capability_providers"
    __table_args__: tuple[UniqueConstraint, Index, Index] = (
        UniqueConstraint("node_id", "capability_id", name="uq_capability_provider_identity"),
        Index("ix_capability_providers_capability_id", "capability_id"),
        Index("ix_capability_providers_node_id", "node_id"),
    )

    provider_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    capability_id: Mapped[str] = mapped_column(String(255), nullable=False)
    definition_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    implementation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reported_status: Mapped[str] = mapped_column(String(32), nullable=False)
    availability: Mapped[str] = mapped_column(String(32), nullable=False)
    first_registered_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    node_lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    node_database_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    node_degraded_reasons_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    unavailability_reason: Mapped[str | None] = mapped_column(Text)


class CapabilityRoutingDecisionRow(Base):
    __tablename__ = "capability_routing_decisions"
    __table_args__: tuple[Index, Index] = (
        Index("ix_capability_routing_provider_id", "provider_id"),
        Index("ix_capability_routing_node_id", "node_id"),
    )

    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    capability_id: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_id: Mapped[str] = mapped_column(
        ForeignKey("capability_providers.provider_id", ondelete="RESTRICT"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    implementation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ResultIngestionRow(Base):
    """Durable canonical Result envelope and semantic processing state."""

    __tablename__ = "result_ingestions"
    __table_args__: tuple[Index, Index] = (
        Index("ix_result_ingestions_status", "status"),
        Index("ix_result_ingestions_transport_message_id", "transport_message_id"),
    )

    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    result_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    transport_message_id: Mapped[str | None] = mapped_column(String(255))
    source_node_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    processing_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    materialized_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unsupported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_conflict_fingerprint: Mapped[str | None] = mapped_column(String(64))
    last_conflict_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
