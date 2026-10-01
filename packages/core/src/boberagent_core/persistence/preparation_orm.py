"""Private Core persistence for M20-E2 preparation admission history."""

from datetime import datetime

from boberagent_contracts import JsonObject
from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .orm import Base
from .types import UTCDateTime


class RuntimePreparationAttemptRow(Base):
    __tablename__ = "runtime_preparation_attempts"
    __table_args__ = (
        UniqueConstraint("request_fingerprint", name="uq_preparation_request_fingerprint"),
        UniqueConstraint("reserved_run_id", name="uq_preparation_reserved_run"),
        CheckConstraint("revision >= 0", name="ck_preparation_revision"),
        CheckConstraint(
            "lifecycle IN ('REQUESTED','DISPATCHED','AWAITING_ARTIFACT','COMPLETED',"
            "'REJECTED','FAILED','INTERRUPTED','CANCELLED')",
            name="ck_preparation_lifecycle",
        ),
        CheckConstraint(
            "(lifecycle = 'REJECTED' AND disposition = 'REJECTED' AND reason_code IS NOT NULL "
            "AND reserved_run_id IS NULL AND permit_id IS NULL AND terminal_at IS NOT NULL) OR "
            "(lifecycle = 'REQUESTED' AND disposition = 'ELIGIBLE' AND reason_code IS NULL "
            "AND reserved_run_id IS NOT NULL AND permit_id IS NOT NULL AND terminal_at IS NULL) OR "
            "(lifecycle IN ('DISPATCHED','AWAITING_ARTIFACT','COMPLETED','FAILED','INTERRUPTED',"
            "'CANCELLED') AND disposition = 'ELIGIBLE' AND reserved_run_id IS NOT NULL "
            "AND permit_id IS NOT NULL)",
            name="ck_preparation_e2_state",
        ),
    )

    preparation_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.mission_id"), nullable=False)
    plan_id: Mapped[str] = mapped_column(ForeignKey("execution_plans.plan_id"), nullable=False)
    plan_intent_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_decision_id: Mapped[str | None] = mapped_column(String(255))
    policy_decision_id: Mapped[str | None] = mapped_column(String(255))
    policy_context_sha256: Mapped[str | None] = mapped_column(String(64))
    approval_decision_id: Mapped[str | None] = mapped_column(String(255))
    acquisition_id: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_artifact_id: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_artifact_id: Mapped[str] = mapped_column(String(255), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_inspection_id: Mapped[str] = mapped_column(String(255), nullable=False)
    semantic_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    classification_inspection_id: Mapped[str] = mapped_column(String(255), nullable=False)
    classification_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_version: Mapped[str | None] = mapped_column(String(128))
    provider_availability: Mapped[str | None] = mapped_column(String(32))
    provider_node_lifecycle: Mapped[str | None] = mapped_column(String(32))
    profile_id: Mapped[str] = mapped_column(String(128), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    reserved_run_id: Mapped[str | None] = mapped_column(String(255))
    permit_id: Mapped[str | None] = mapped_column(String(255))
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    context_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    spec_json: Mapped[JsonObject | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    terminal_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PreparationPermitRow(Base):
    __tablename__ = "preparation_permits"
    __table_args__ = (
        UniqueConstraint("preparation_id", name="uq_preparation_permit_attempt"),
        UniqueConstraint("reserved_run_id", name="uq_preparation_permit_run"),
    )

    permit_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    preparation_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_preparation_attempts.preparation_id"), nullable=False
    )
    reserved_run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class PreparationImportProgressRow(Base):
    __tablename__ = "preparation_import_progress"
    __table_args__ = (
        UniqueConstraint("preparation_id", "artifact_id", name="uq_preparation_import_artifact"),
        CheckConstraint(
            "received_bytes >= 0 AND received_bytes <= size_bytes",
            name="ck_core_preparation_import_bounds",
        ),
    )

    import_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    preparation_id: Mapped[str] = mapped_column(
        ForeignKey("runtime_preparation_attempts.preparation_id"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    received_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
