"""Persistence primitives only; no planner, validator, policy evaluator or dispatcher."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from sqlite3 import Connection as SQLiteConnection
from typing import cast

from boberagent_contracts import ExecutionPlanRef, ExecutionPlanV2, JsonObject, Sha256Digest
from boberagent_contracts.execution_plan_v2 import execution_intent_digest
from boberagent_contracts.plan_canonical import canonical_digest
from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from boberagent_core.persistence.planning_orm import (
    REUSABLE_STATES,
    ExecutionPlanRow,
    PlanDecisionRow,
    PlanningAttemptRow,
)

from .errors import PlanningConflict, PlanningPersistenceError
from .fingerprints import decision_context_fingerprint, planning_request_fingerprint
from .models import (
    PlanningAttempt,
    PlanningAttemptLifecycle,
    PlanningAttemptRef,
    PlanningDisposition,
    PlanningRequest,
    PlanProposalRevision,
    PlanValidation,
)
from .records import PlanDecisionRecord, PlanDecisionRef, ProposalHistory, StoredExecutionPlan

_json: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)
_digest: TypeAdapter[str] = TypeAdapter(Sha256Digest)
_TRANSITIONS = {
    PlanningAttemptLifecycle.REQUESTED: {
        PlanningAttemptLifecycle.EVALUATING,
        PlanningAttemptLifecycle.COMPLETED,
        PlanningAttemptLifecycle.FAILED,
        PlanningAttemptLifecycle.CANCELLED,
    },
    PlanningAttemptLifecycle.EVALUATING: {
        PlanningAttemptLifecycle.WAITING_INPUT,
        PlanningAttemptLifecycle.COMPLETED,
        PlanningAttemptLifecycle.FAILED,
        PlanningAttemptLifecycle.INTERRUPTED,
        PlanningAttemptLifecycle.CANCELLED,
    },
    PlanningAttemptLifecycle.WAITING_INPUT: {
        PlanningAttemptLifecycle.EVALUATING,
        PlanningAttemptLifecycle.FAILED,
        PlanningAttemptLifecycle.CANCELLED,
    },
}


def _document(model: BaseModel) -> JsonObject:
    return _json.validate_json(model.model_dump_json())


@contextmanager
def _atomic(session: Session) -> Iterator[None]:
    # Python sqlite legacy transaction mode does not BEGIN for SAVEPOINT. Ensure release of
    # our savepoint cannot commit outside the caller's CoreUnitOfWork transaction.
    connection = session.connection()
    driver = cast(SQLiteConnection, connection.connection.driver_connection)
    if not driver.in_transaction:
        connection.exec_driver_sql("BEGIN")
    try:
        with session.begin_nested():
            yield
    except IntegrityError:
        raise PlanningConflict("planning persistence integrity constraint failed") from None


@contextmanager
def _read_guard() -> Iterator[None]:
    try:
        yield
    except (ValueError, TypeError):
        raise PlanningPersistenceError(
            "corrupt or unsupported persisted planning document"
        ) from None


def _request_columns(request: PlanningRequest) -> dict[str, object]:
    inspection = request.inspection
    if canonical_digest(inspection.classification) != inspection.classification_sha256:
        raise PlanningPersistenceError("C3 classification document digest mismatch")
    return {
        "mission_id": str(request.mission_ref),
        "hypothesis_id": str(request.hypothesis_ref),
        "candidate_id": str(request.candidate_ref),
        "acquisition_id": str(request.source.acquisition_ref),
        "semantic_inspection_id": str(inspection.classification.semantic_inspection_ref),
        "classification_inspection_id": str(inspection.classification_ref),
        "semantic_sha256": inspection.classification.semantic_document_sha256,
        "classification_sha256": inspection.classification_sha256,
        "planner_profile": request.profile,
        "planner_version": request.profile_version,
        "policy_profile": request.policy_profile,
        "policy_version": request.policy_version,
        "request_fingerprint": planning_request_fingerprint(request),
    }


def _attempt_state(attempt: PlanningAttempt) -> dict[str, object]:
    return {
        "lifecycle": attempt.lifecycle.value,
        "disposition": None if attempt.disposition is None else attempt.disposition.value,
        "revision_number": len(attempt.revisions),
        "history_json": _document(ProposalHistory(revisions=attempt.revisions)),
        "failure_code": attempt.failure_code,
        "diagnostic_codes_json": list(attempt.diagnostic_codes),
        "updated_at": attempt.updated_at,
        "completed_at": attempt.completed_at,
    }


def _strict_plan(plan: ExecutionPlanV2) -> ExecutionPlanV2:
    if not isinstance(plan, ExecutionPlanV2):
        raise PlanningPersistenceError("finalized persistence requires ExecutionPlanV2")
    try:
        return ExecutionPlanV2.model_validate_json(plan.model_dump_json())
    except (ValidationError, ValueError, TypeError):
        raise PlanningPersistenceError("invalid ExecutionPlanV2 document") from None


def _load_plan(row: ExecutionPlanRow) -> StoredExecutionPlan:
    try:
        plan_json = _json.validate_python(row.plan_json)
        if (
            row.schema_version != "execution-plan-v2"
            or plan_json.get("schema_version") != row.schema_version
        ):
            raise ValueError("unsupported schema")
        plan = ExecutionPlanV2.model_validate(plan_json)
        if (
            str(plan.execution_plan_id) != row.plan_id
            or str(plan.mission_ref) != row.mission_id
            or plan.created_at != row.created_at
            or execution_intent_digest(plan) != row.intent_sha256
        ):
            raise ValueError("intent mismatch")
        return StoredExecutionPlan(
            planning_attempt_ref=PlanningAttemptRef(row.attempt_id),
            plan=plan,
            intent_sha256=row.intent_sha256,
            supersedes_plan_ref=(
                None if row.supersedes_plan_id is None else ExecutionPlanRef(row.supersedes_plan_id)
            ),
        )
    except (ValidationError, ValueError, TypeError):
        raise PlanningPersistenceError("corrupt or unsupported persisted execution plan") from None


class PlanningAttemptRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, attempt: PlanningAttempt) -> PlanningAttempt:
        """Insert or return the existing reusable determination, atomically by fingerprint.

        Deliberate new IDs may follow FAILED/INTERRUPTED/CANCELLED. No automatic retry occurs.
        Caller-generated identity/time do not alter reusable request identity.
        """
        try:
            attempt = PlanningAttempt.model_validate_json(attempt.model_dump_json())
        except (ValidationError, ValueError, TypeError):
            raise PlanningPersistenceError("invalid planning attempt document") from None
        if attempt.finalized_plan is not None or attempt.disposition is PlanningDisposition.VALID:
            raise PlanningConflict("use explicit atomic finalization for VALID intent")
        attempt = self._checked_timestamps(attempt)
        columns = _request_columns(attempt.request)
        self._verify_revisions(attempt)
        with _atomic(self._session):
            self._session.execute(
                insert(PlanningAttemptRow)
                .values(
                    **columns,
                    **_attempt_state(attempt),
                    attempt_id=str(attempt.planning_attempt_ref),
                    schema_version="planning-attempt-v1",
                    request_json=_document(attempt.request),
                    created_at=attempt.created_at,
                )
                .on_conflict_do_nothing()
            )
            existing = self.get(attempt.planning_attempt_ref)
            if existing is not None:
                if planning_request_fingerprint(existing.request) != columns["request_fingerprint"]:
                    raise PlanningConflict("PlanningAttemptRef identifies a different request")
                return existing
            reusable = self.find_reusable_by_fingerprint(str(columns["request_fingerprint"]))
            if reusable is None:
                raise PlanningConflict("planning attempt creation conflicted")
            return reusable

    def get(self, attempt_ref: PlanningAttemptRef) -> PlanningAttempt | None:
        with _read_guard():
            row = self._session.get(PlanningAttemptRow, str(attempt_ref), populate_existing=True)
        if row is None:
            return None
        try:
            request_json = _json.validate_python(row.request_json)
            history_json = _json.validate_python(row.history_json)
            if row.schema_version != "planning-attempt-v1":
                raise ValueError("unsupported schema")
            if (
                request_json.get("profile") != row.planner_profile
                or request_json.get("profile_version") != row.planner_version
                or history_json.get("schema_version") != "plan-proposal-history-v1"
            ):
                raise ValueError("document version mismatch")
            request = PlanningRequest.model_validate(request_json)
            history = ProposalHistory.model_validate(history_json)
            if any(getattr(row, key) != value for key, value in _request_columns(request).items()):
                raise ValueError("request identity mismatch")
            if row.revision_number != len(history.revisions):
                raise ValueError("revision mismatch")
            stored = ExecutionPlanRepository(self._session).get_by_attempt(attempt_ref)
            attempt = PlanningAttempt(
                planning_attempt_ref=attempt_ref,
                request=request,
                lifecycle=PlanningAttemptLifecycle(row.lifecycle),
                disposition=None
                if row.disposition is None
                else PlanningDisposition(row.disposition),
                revisions=history.revisions,
                finalized_plan=None if stored is None else stored.plan,
                failure_code=row.failure_code,
                diagnostic_codes=tuple(row.diagnostic_codes_json),
                created_at=row.created_at,
                updated_at=row.updated_at,
                completed_at=row.completed_at,
            )
            if attempt.lifecycle.is_terminal != (attempt.completed_at is not None):
                raise ValueError("completion time mismatch")
            self._checked_timestamps(attempt)
            self._verify_revisions(attempt)
            return attempt
        except (ValidationError, ValueError, TypeError, KeyError):
            raise PlanningPersistenceError(
                "corrupt or unsupported persisted planning attempt"
            ) from None

    def find_reusable_by_fingerprint(self, fingerprint: str) -> PlanningAttempt | None:
        try:
            _digest.validate_python(fingerprint)
        except ValidationError:
            raise PlanningPersistenceError("invalid request fingerprint") from None
        ref = self._session.scalar(
            select(PlanningAttemptRow.attempt_id).where(
                PlanningAttemptRow.request_fingerprint == fingerprint,
                PlanningAttemptRow.lifecycle.in_(REUSABLE_STATES),
            )
        )
        return None if ref is None else self.get(PlanningAttemptRef(ref))

    def update_lifecycle(
        self,
        attempt_ref: PlanningAttemptRef,
        lifecycle: PlanningAttemptLifecycle,
        *,
        expected_state: PlanningAttemptLifecycle,
        expected_revision: int,
        updated_at: datetime,
        disposition: PlanningDisposition | None = None,
        failure_code: str | None = None,
        diagnostic_codes: tuple[str, ...] = (),
    ) -> PlanningAttempt:
        old = self._required(attempt_ref)
        if lifecycle not in _TRANSITIONS.get(old.lifecycle, set()):
            raise PlanningConflict("forbidden planning lifecycle transition")
        if disposition is PlanningDisposition.VALID:
            raise PlanningConflict("VALID requires explicit atomic plan finalization")
        if (
            lifecycle is PlanningAttemptLifecycle.WAITING_INPUT
            and disposition is not PlanningDisposition.REQUIRES_INPUT
        ):
            raise PlanningConflict("WAITING_INPUT requires REQUIRES_INPUT")
        if lifecycle is PlanningAttemptLifecycle.COMPLETED and disposition not in {
            PlanningDisposition.UNSUPPORTED,
            PlanningDisposition.INVALID,
        }:
            raise PlanningConflict("non-plan completion requires UNSUPPORTED or INVALID")
        new = self._replace(
            old,
            lifecycle=lifecycle,
            disposition=disposition,
            updated_at=updated_at,
            completed_at=updated_at if lifecycle.is_terminal else None,
            failure_code=failure_code,
            diagnostic_codes=diagnostic_codes,
        )
        self._compare_and_set(old, new, expected_state, expected_revision)
        return new

    def update_proposal(
        self,
        revision: PlanProposalRevision,
        *,
        expected_state: PlanningAttemptLifecycle,
        expected_revision: int,
    ) -> PlanningAttempt:
        try:
            revision = PlanProposalRevision.model_validate_json(revision.model_dump_json())
        except (ValidationError, ValueError, TypeError):
            raise PlanningPersistenceError("invalid proposal revision document") from None
        old = self._required(revision.planning_attempt_ref)
        if old.finalized_plan is not None or revision.proposal.source != old.request.source:
            raise PlanningConflict("proposal cannot change finalized intent or source pins")
        new = self._replace(
            old, revisions=(*old.revisions, revision), updated_at=revision.created_at
        )
        self._verify_revisions(new)
        self._compare_and_set(old, new, expected_state, expected_revision)
        return new

    def finalize(
        self,
        attempt_ref: PlanningAttemptRef,
        plan: ExecutionPlanV2,
        *,
        intent_sha256: str,
        expected_state: PlanningAttemptLifecycle,
        expected_revision: int,
        completed_at: datetime,
        supersedes_plan_ref: ExecutionPlanRef | None = None,
    ) -> StoredExecutionPlan:
        """Persist supplied intent and completion atomically. Does not assess its authority."""
        with _atomic(self._session):
            old = self._required(attempt_ref)
            if PlanningAttemptLifecycle.COMPLETED not in _TRANSITIONS.get(old.lifecycle, set()):
                raise PlanningConflict("attempt cannot finalize from current lifecycle")
            stored = ExecutionPlanRepository(self._session).add_finalized(
                attempt_ref,
                plan,
                intent_sha256=intent_sha256,
                supersedes_plan_ref=supersedes_plan_ref,
            )
            new = self._replace(
                old,
                lifecycle=PlanningAttemptLifecycle.COMPLETED,
                disposition=PlanningDisposition.VALID,
                finalized_plan=stored.plan,
                updated_at=completed_at,
                completed_at=completed_at,
            )
            self._compare_and_set(old, new, expected_state, expected_revision)
            return stored

    def recover_unproven_active_attempts(self, *, cutoff: datetime, recovered_at: datetime) -> int:
        """Explicitly interrupt EVALUATING rows at/before cutoff; never resume/rerun/wait."""
        refs = tuple(
            self._session.scalars(
                select(PlanningAttemptRow.attempt_id)
                .where(
                    PlanningAttemptRow.lifecycle == PlanningAttemptLifecycle.EVALUATING.value,
                    PlanningAttemptRow.updated_at <= cutoff,
                )
                .order_by(PlanningAttemptRow.attempt_id)
            )
        )
        with _atomic(self._session):
            for ref in refs:
                old = self._required(PlanningAttemptRef(ref))
                self.update_lifecycle(
                    old.planning_attempt_ref,
                    PlanningAttemptLifecycle.INTERRUPTED,
                    expected_state=PlanningAttemptLifecycle.EVALUATING,
                    expected_revision=len(old.revisions),
                    updated_at=recovered_at,
                    disposition=old.disposition,
                    failure_code="UNPROVEN_EVALUATION",
                )
        return len(refs)

    def _required(self, ref: PlanningAttemptRef) -> PlanningAttempt:
        attempt = self.get(ref)
        if attempt is None:
            raise KeyError("unknown PlanningAttempt")
        return attempt

    @staticmethod
    def _checked_timestamps(attempt: PlanningAttempt) -> PlanningAttempt:
        if (
            attempt.lifecycle is PlanningAttemptLifecycle.WAITING_INPUT
            and attempt.disposition is not PlanningDisposition.REQUIRES_INPUT
        ):
            raise PlanningConflict("WAITING_INPUT requires REQUIRES_INPUT")
        if (
            attempt.disposition is PlanningDisposition.VALID
            and attempt.lifecycle is not PlanningAttemptLifecycle.COMPLETED
        ):
            raise PlanningConflict("VALID requires terminal completion")
        if (
            attempt.lifecycle is PlanningAttemptLifecycle.COMPLETED
            and attempt.disposition is PlanningDisposition.REQUIRES_INPUT
        ):
            raise PlanningConflict("unresolved input is not a completed determination")
        if attempt.updated_at < attempt.created_at:
            raise PlanningConflict("planning timestamps cannot move backwards")
        if attempt.completed_at is not None and (
            not attempt.lifecycle.is_terminal or attempt.completed_at != attempt.updated_at
        ):
            raise PlanningConflict("invalid planning completion time")
        if attempt.lifecycle.is_terminal and attempt.completed_at is None:
            return PlanningAttempt.model_validate(
                {**attempt.model_dump(), "completed_at": attempt.updated_at}
            )
        return attempt

    @staticmethod
    def _replace(old: PlanningAttempt, **changes: object) -> PlanningAttempt:
        try:
            new = PlanningAttempt.model_validate({**old.model_dump(), **changes})
            if new.updated_at < old.updated_at:
                raise ValueError("time moved backwards")
            return PlanningAttemptRepository._checked_timestamps(new)
        except (ValidationError, ValueError, TypeError):
            raise PlanningConflict("invalid planning state or revision update") from None

    @staticmethod
    def _verify_revisions(attempt: PlanningAttempt) -> None:
        previous = None
        timestamp = attempt.created_at
        for revision in attempt.revisions:
            if (
                revision.previous_revision_digest != previous
                or revision.proposal.source != attempt.request.source
            ):
                raise PlanningConflict("proposal revision chain or source mismatch")
            if revision.created_at < timestamp or revision.created_at > attempt.updated_at:
                raise PlanningConflict("invalid revision timestamp")
            previous = canonical_digest(revision)
            timestamp = revision.created_at

    def _compare_and_set(
        self,
        old: PlanningAttempt,
        new: PlanningAttempt,
        expected_state: PlanningAttemptLifecycle,
        expected_revision: int,
    ) -> None:
        if (
            old.lifecycle.is_terminal
            or old.lifecycle is not expected_state
            or len(old.revisions) != expected_revision
        ):
            raise PlanningConflict("stale or terminal planning attempt")
        with _atomic(self._session):
            result = self._session.connection().execute(
                update(PlanningAttemptRow)
                .where(
                    PlanningAttemptRow.attempt_id == str(old.planning_attempt_ref),
                    PlanningAttemptRow.lifecycle == expected_state.value,
                    PlanningAttemptRow.revision_number == expected_revision,
                    PlanningAttemptRow.updated_at == old.updated_at,
                )
                .values(**_attempt_state(new))
            )
            if result.rowcount != 1:
                raise PlanningConflict("stale planning state or proposal revision")


class ExecutionPlanRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_finalized(
        self,
        attempt_ref: PlanningAttemptRef,
        plan: ExecutionPlanV2,
        *,
        intent_sha256: str,
        supersedes_plan_ref: ExecutionPlanRef | None = None,
    ) -> StoredExecutionPlan:
        plan = _strict_plan(plan)
        if execution_intent_digest(plan) != intent_sha256:
            raise PlanningPersistenceError("supplied execution intent digest mismatch")
        attempt = PlanningAttemptRepository(self._session)._required(attempt_ref)
        request = attempt.request
        if attempt.lifecycle not in {
            PlanningAttemptLifecycle.REQUESTED,
            PlanningAttemptLifecycle.EVALUATING,
        } or (
            plan.source != request.source
            or plan.mission_ref != request.mission_ref
            or request.inspection.classification.classification.value == "UNSUPPORTED"
        ):
            raise PlanningConflict("intent cannot finalize this attempt or change its identity")
        if supersedes_plan_ref is not None:
            old_plan = self.get(supersedes_plan_ref)
            if (
                old_plan is None
                or old_plan.plan.mission_ref != plan.mission_ref
                or supersedes_plan_ref == plan.execution_plan_id
            ):
                raise PlanningConflict("invalid superseded plan identity")
        stored = StoredExecutionPlan(
            planning_attempt_ref=attempt_ref,
            plan=plan,
            intent_sha256=intent_sha256,
            supersedes_plan_ref=supersedes_plan_ref,
        )
        with _atomic(self._session):
            self._session.execute(
                insert(ExecutionPlanRow)
                .values(
                    plan_id=str(plan.execution_plan_id),
                    mission_id=str(plan.mission_ref),
                    attempt_id=str(attempt_ref),
                    schema_version=plan.schema_version,
                    intent_sha256=intent_sha256,
                    plan_json=_document(plan),
                    supersedes_plan_id=None
                    if supersedes_plan_ref is None
                    else str(supersedes_plan_ref),
                    created_at=plan.created_at,
                )
                .on_conflict_do_nothing()
            )
            loaded = self.get(plan.execution_plan_id)
            if loaded != stored:
                raise PlanningConflict("finalized plan identity or attempt already exists")
        return stored

    def get(self, plan_ref: ExecutionPlanRef) -> StoredExecutionPlan | None:
        with _read_guard():
            row = self._session.get(ExecutionPlanRow, str(plan_ref), populate_existing=True)
            return None if row is None else _load_plan(row)

    def get_by_attempt(self, attempt_ref: PlanningAttemptRef) -> StoredExecutionPlan | None:
        with _read_guard():
            row = self._session.scalar(
                select(ExecutionPlanRow)
                .where(ExecutionPlanRow.attempt_id == str(attempt_ref))
                .execution_options(populate_existing=True)
            )
            return None if row is None else _load_plan(row)

    def get_by_intent_digest(self, digest: str) -> tuple[StoredExecutionPlan, ...]:
        with _read_guard():
            rows = self._session.scalars(
                select(ExecutionPlanRow)
                .where(ExecutionPlanRow.intent_sha256 == digest)
                .order_by(ExecutionPlanRow.plan_id)
                .execution_options(populate_existing=True)
            )
            return tuple(_load_plan(row) for row in rows)


class PlanDecisionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, record: PlanDecisionRecord) -> PlanDecisionRecord:
        try:
            record = PlanDecisionRecord.model_validate_json(record.model_dump_json())
        except (ValidationError, ValueError, TypeError):
            raise PlanningPersistenceError("invalid plan decision document") from None
        plan = ExecutionPlanRepository(self._session).get(record.document.value.execution_plan_ref)
        if plan is None:
            raise KeyError("unknown ExecutionPlan")
        attempt = PlanningAttemptRepository(self._session)._required(plan.planning_attempt_ref)
        if (
            plan.intent_sha256 != record.document.value.intent_sha256
            or plan.plan.mission_ref != record.context.mission_ref
            or attempt.request.inspection.classification_sha256
            != record.context.classification_sha256
        ):
            raise PlanningConflict("decision does not bind the exact plan and inspection")
        profile, version = _evaluator(record)
        with _atomic(self._session):
            self._session.execute(
                insert(PlanDecisionRow)
                .values(
                    decision_id=str(record.decision_ref),
                    plan_id=str(plan.plan.execution_plan_id),
                    intent_sha256=plan.intent_sha256,
                    kind=record.document.kind,
                    schema_version=record.schema_version,
                    evaluator_profile=profile,
                    evaluator_version=version,
                    context_fingerprint=decision_context_fingerprint(record.context),
                    record_json=_document(record),
                    created_at=record.created_at,
                )
                .on_conflict_do_nothing()
            )
            loaded = self.get(record.decision_ref)
            if loaded != record:
                raise PlanningConflict("PlanDecisionRef identifies a different immutable record")
        return record

    def get(self, ref: PlanDecisionRef) -> PlanDecisionRecord | None:
        with _read_guard():
            row = self._session.get(PlanDecisionRow, str(ref), populate_existing=True)
            return None if row is None else self._load(row)

    def list_for_plan(self, plan_ref: ExecutionPlanRef) -> tuple[PlanDecisionRecord, ...]:
        return self._list(plan_ref)

    def find_by_context(
        self, plan_ref: ExecutionPlanRef, fingerprint: str
    ) -> tuple[PlanDecisionRecord, ...]:
        """History lookup only, never an applicability/authorization decision."""
        return self._list(plan_ref, fingerprint)

    def _list(
        self, ref: ExecutionPlanRef, fingerprint: str | None = None
    ) -> tuple[PlanDecisionRecord, ...]:
        query = select(PlanDecisionRow).where(PlanDecisionRow.plan_id == str(ref))
        if fingerprint is not None:
            query = query.where(PlanDecisionRow.context_fingerprint == fingerprint)
        with _read_guard():
            rows = self._session.scalars(
                query.order_by(
                    PlanDecisionRow.created_at, PlanDecisionRow.decision_id
                ).execution_options(populate_existing=True)
            )
            return tuple(self._load(row) for row in rows)

    def _load(self, row: PlanDecisionRow) -> PlanDecisionRecord:
        try:
            record_json = _json.validate_python(row.record_json)
            if (
                row.schema_version != "plan-decision-v1"
                or record_json.get("schema_version") != row.schema_version
            ):
                raise ValueError("unsupported schema")
            record = PlanDecisionRecord.model_validate(record_json)
            profile, version = _evaluator(record)
            value = record.document.value
            plan = ExecutionPlanRepository(self._session).get(value.execution_plan_ref)
            if (
                str(record.decision_ref) != row.decision_id
                or str(value.execution_plan_ref) != row.plan_id
                or value.intent_sha256 != row.intent_sha256
                or record.document.kind != row.kind
                or profile != row.evaluator_profile
                or version != row.evaluator_version
                or decision_context_fingerprint(record.context) != row.context_fingerprint
                or record.created_at != row.created_at
                or plan is None
                or plan.intent_sha256 != value.intent_sha256
                or plan.plan.mission_ref != value.mission_ref
            ):
                raise ValueError("decision identity mismatch")
            return record
        except (ValidationError, ValueError, TypeError):
            raise PlanningPersistenceError(
                "corrupt or unsupported persisted plan decision"
            ) from None


def _evaluator(record: PlanDecisionRecord) -> tuple[str, str]:
    value = record.document.value
    if isinstance(value, PlanValidation):
        return value.validation_profile, value.validation_version
    return value.policy_profile, value.policy_version
