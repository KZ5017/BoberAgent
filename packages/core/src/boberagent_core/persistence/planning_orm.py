"""Private Core mappings for M20-D2 history; no execution or policy authority."""

from datetime import datetime

from boberagent_contracts import JsonObject
from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .orm import Base
from .types import UTCDateTime

REUSABLE_STATES = ("REQUESTED", "EVALUATING", "WAITING_INPUT", "COMPLETED")


class PlanningAttemptRow(Base):
    __tablename__ = "planning_attempts"
    __table_args__ = (
        Index(
            "uq_planning_attempt_reusable_request",
            "request_fingerprint",
            unique=True,
            sqlite_where=text(
                "lifecycle IN ('REQUESTED','EVALUATING','WAITING_INPUT','COMPLETED')"
            ),
        ),
        CheckConstraint("revision_number >= 0", name="ck_planning_revision"),
        CheckConstraint(
            "lifecycle IN ('REQUESTED','EVALUATING','WAITING_INPUT','COMPLETED',"
            "'FAILED','INTERRUPTED','CANCELLED')",
            name="ck_planning_lifecycle",
        ),
        CheckConstraint(
            "disposition IS NULL OR disposition IN ('VALID','REQUIRES_INPUT','UNSUPPORTED','INVALID')",
            name="ck_planning_disposition",
        ),
        CheckConstraint(
            "(lifecycle IN ('COMPLETED','FAILED','INTERRUPTED','CANCELLED')) = "
            "(completed_at IS NOT NULL)",
            name="ck_planning_completion_time",
        ),
        CheckConstraint(
            "lifecycle != 'COMPLETED' OR disposition IS NOT NULL",
            name="ck_planning_completed_disposition",
        ),
        CheckConstraint(
            "disposition != 'VALID' OR lifecycle = 'COMPLETED'",
            name="ck_planning_valid_terminal",
        ),
    )

    attempt_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.mission_id"), nullable=False)
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("vulnerability_hypotheses.hypothesis_id"), nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("poc_candidates.candidate_id"), nullable=False
    )
    acquisition_id: Mapped[str] = mapped_column(
        ForeignKey("poc_acquisitions.acquisition_id"), nullable=False
    )
    semantic_inspection_id: Mapped[str] = mapped_column(
        ForeignKey("poc_inspections.inspection_id"), nullable=False
    )
    classification_inspection_id: Mapped[str] = mapped_column(
        ForeignKey("poc_inspections.inspection_id"), nullable=False
    )
    semantic_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    classification_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    planner_profile: Mapped[str] = mapped_column(String(128), nullable=False)
    planner_version: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_profile: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    history_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    disposition: Mapped[str | None] = mapped_column(String(32))
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    diagnostic_codes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ExecutionPlanRow(Base):
    __tablename__ = "execution_plans"
    __table_args__ = (
        UniqueConstraint("attempt_id", name="uq_execution_plan_attempt"),
        Index("ix_execution_plan_intent", "intent_sha256"),
    )

    plan_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.mission_id"), nullable=False)
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("planning_attempts.attempt_id"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    supersedes_plan_id: Mapped[str | None] = mapped_column(ForeignKey("execution_plans.plan_id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class PlanDecisionRow(Base):
    __tablename__ = "plan_decisions"
    __table_args__ = (
        CheckConstraint("kind IN ('VALIDATION','POLICY','APPROVAL')", name="ck_plan_decision_kind"),
        Index("ix_plan_decision_context", "plan_id", "context_fingerprint"),
    )

    decision_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("execution_plans.plan_id"), nullable=False)
    intent_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluator_profile: Mapped[str] = mapped_column(String(128), nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(128), nullable=False)
    context_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    record_json: Mapped[JsonObject] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
