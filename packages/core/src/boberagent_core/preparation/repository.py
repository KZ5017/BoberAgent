"""Atomic Core E2 history persistence; no routing, source access or Node calls."""

from collections.abc import Iterator
from contextlib import contextmanager
from sqlite3 import Connection as SQLiteConnection
from typing import cast

from boberagent_contracts import (
    JsonObject,
    PreparationPermit,
    PreparationPermitRef,
    RuntimePreparationRef,
    RuntimePreparationSpec,
)
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_contracts.runtime_preparation import preparation_permit_digest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from boberagent_core.persistence.preparation_orm import (
    PreparationPermitRow,
    RuntimePreparationAttemptRow,
)

from .models import PreparationAttempt, PreparationContext, PreparationLifecycle

_json: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class PreparationPersistenceError(ValueError):
    """Persisted E2 identity or strict document failed verification."""


class PreparationConflict(ValueError):
    """An E2 identity/CAS assertion conflicts with immutable history."""


@contextmanager
def _atomic(session: Session) -> Iterator[None]:
    # SQLite legacy mode needs an explicit outer BEGIN before a SAVEPOINT, as in D2.
    connection = session.connection()
    driver = cast(SQLiteConnection, connection.connection.driver_connection)
    if not driver.in_transaction:
        connection.exec_driver_sql("BEGIN")
    try:
        with session.begin_nested():
            yield
    except IntegrityError:
        raise PreparationConflict("preparation persistence integrity constraint failed") from None


def _document(
    value: PreparationContext | RuntimePreparationSpec | PreparationPermit,
) -> JsonObject:
    return _json.validate_json(value.model_dump_json())


class RuntimePreparationRepository:
    """One request fingerprint, one immutable permit, all under the caller's UoW."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self, attempt: PreparationAttempt, permit: PreparationPermit | None
    ) -> tuple[PreparationAttempt, PreparationPermit | None]:
        try:
            attempt = PreparationAttempt.model_validate_json(attempt.model_dump_json())
            permit = (
                None
                if permit is None
                else PreparationPermit.model_validate_json(permit.model_dump_json())
            )
        except (ValidationError, ValueError, TypeError):
            raise PreparationPersistenceError("invalid preparation document") from None
        if attempt.request_fingerprint != canonical_digest(attempt.context):
            raise PreparationConflict("request fingerprint does not bind the exact context")
        if (attempt.lifecycle is PreparationLifecycle.REQUESTED) != (permit is not None):
            raise PreparationConflict("permit is required exactly for an eligible request")
        if permit is not None and (
            permit.permit_ref != attempt.permit_ref
            or permit.run_ref != attempt.reserved_run_ref
            or permit.spec != attempt.spec
        ):
            raise PreparationConflict("permit does not bind the attempt")
        context = attempt.context
        source = context.source
        with _atomic(self._session):
            self._session.execute(
                insert(RuntimePreparationAttemptRow)
                .values(
                    preparation_id=str(attempt.preparation_ref),
                    mission_id=str(context.request.mission_ref),
                    plan_id=str(context.request.plan_ref),
                    plan_intent_sha256=context.plan_intent_sha256,
                    validation_decision_id=(
                        None
                        if context.validation_decision_ref is None
                        else str(context.validation_decision_ref)
                    ),
                    policy_decision_id=(
                        None
                        if context.policy_decision_ref is None
                        else str(context.policy_decision_ref)
                    ),
                    policy_context_sha256=context.policy_context_sha256,
                    approval_decision_id=(
                        None
                        if context.approval_decision_ref is None
                        else str(context.approval_decision_ref)
                    ),
                    acquisition_id=str(source.acquisition_ref),
                    raw_artifact_id=str(source.raw_artifact_ref),
                    raw_sha256=source.raw_sha256,
                    manifest_artifact_id=str(source.manifest_artifact_ref),
                    manifest_sha256=source.manifest_sha256,
                    semantic_inspection_id=str(context.semantic_inspection_ref),
                    semantic_sha256=context.semantic_sha256,
                    classification_inspection_id=str(context.classification_inspection_ref),
                    classification_sha256=context.classification_sha256,
                    node_id=context.request.node_id,
                    provider_id=str(context.request.provider_id),
                    provider_version=context.provider_version,
                    provider_availability=(
                        None
                        if context.provider_availability is None
                        else context.provider_availability.value
                    ),
                    provider_node_lifecycle=context.provider_node_lifecycle,
                    profile_id=context.request.profile_id,
                    profile_version=context.request.profile_version,
                    profile_sha256=context.profile_sha256,
                    request_fingerprint=attempt.request_fingerprint,
                    reserved_run_id=(
                        None if attempt.reserved_run_ref is None else str(attempt.reserved_run_ref)
                    ),
                    permit_id=None if attempt.permit_ref is None else str(attempt.permit_ref),
                    lifecycle=attempt.lifecycle.value,
                    disposition=attempt.disposition.value,
                    reason_code=None if attempt.reason_code is None else attempt.reason_code.value,
                    revision=attempt.revision,
                    context_json=_document(context),
                    spec_json=None if attempt.spec is None else _document(attempt.spec),
                    created_at=attempt.created_at,
                    updated_at=attempt.updated_at,
                    terminal_at=attempt.terminal_at,
                )
                .on_conflict_do_nothing(index_elements=["request_fingerprint"])
            )
            found = self.find_by_fingerprint(attempt.request_fingerprint)
            if found is None:
                raise PreparationPersistenceError("preparation insert vanished")
            if found.preparation_ref != attempt.preparation_ref:
                historical = self.get_permit(found.permit_ref) if found.permit_ref else None
                return found, historical
            if permit is not None:
                self._session.add(
                    PreparationPermitRow(
                        permit_id=str(permit.permit_ref),
                        preparation_id=str(attempt.preparation_ref),
                        reserved_run_id=str(permit.run_ref),
                        authority_sha256=preparation_permit_digest(permit),
                        request_fingerprint=attempt.request_fingerprint,
                        permit_json=_document(permit),
                        issued_at=permit.issued_at,
                        expires_at=permit.expires_at,
                    )
                )
                self._session.flush()
            return found, permit

    def get(self, ref: RuntimePreparationRef) -> PreparationAttempt | None:
        row = self._session.get(RuntimePreparationAttemptRow, str(ref), populate_existing=True)
        return None if row is None else self._load(row)

    def find_by_fingerprint(self, fingerprint: str) -> PreparationAttempt | None:
        row = self._session.scalar(
            select(RuntimePreparationAttemptRow)
            .where(RuntimePreparationAttemptRow.request_fingerprint == fingerprint)
            .execution_options(populate_existing=True)
        )
        return None if row is None else self._load(row)

    def get_permit(self, ref: PreparationPermitRef) -> PreparationPermit | None:
        row = self._session.get(PreparationPermitRow, str(ref), populate_existing=True)
        if row is None:
            return None
        try:
            body = _json.validate_python(row.permit_json)
            permit = PreparationPermit.model_validate(body)
            attempt = self.get(RuntimePreparationRef(row.preparation_id))
            if (
                str(permit.permit_ref) != row.permit_id
                or str(permit.run_ref) != row.reserved_run_id
                or permit.issued_at != row.issued_at
                or permit.expires_at != row.expires_at
                or preparation_permit_digest(permit) != row.authority_sha256
                or attempt is None
                or attempt.permit_ref != permit.permit_ref
                or attempt.request_fingerprint != row.request_fingerprint
                or attempt.spec != permit.spec
            ):
                raise ValueError("permit identity mismatch")
            return permit
        except (ValidationError, ValueError, TypeError):
            raise PreparationPersistenceError("corrupt or unsupported preparation permit") from None

    def compare_and_set_revision(
        self, ref: RuntimePreparationRef, *, expected_revision: int, updated_at: object
    ) -> PreparationAttempt:
        """Internal CAS primitive reserved for later explicit state transitions; no dispatch."""
        from datetime import datetime

        if not isinstance(updated_at, datetime):
            raise PreparationConflict("invalid CAS timestamp")
        current = self.get(ref)
        if current is None or current.lifecycle is not PreparationLifecycle.REQUESTED:
            raise PreparationConflict("preparation is not an active request")
        if updated_at < current.updated_at:
            raise PreparationConflict("preparation timestamp cannot regress")
        result = self._session.execute(
            update(RuntimePreparationAttemptRow)
            .where(
                RuntimePreparationAttemptRow.preparation_id == str(ref),
                RuntimePreparationAttemptRow.lifecycle == PreparationLifecycle.REQUESTED.value,
                RuntimePreparationAttemptRow.revision == expected_revision,
            )
            .values(revision=expected_revision + 1, updated_at=updated_at)
        )
        if getattr(result, "rowcount", None) != 1:
            raise PreparationConflict("stale preparation CAS revision")
        loaded = self.get(ref)
        assert loaded is not None
        return loaded

    def mark_dispatched(
        self, ref: RuntimePreparationRef, *, expected_revision: int, updated_at: object
    ) -> PreparationAttempt:
        """CAS the reserved Run identity into a submitted preparation lifecycle."""
        from datetime import datetime

        if not isinstance(updated_at, datetime):
            raise PreparationConflict("invalid dispatch timestamp")
        current = self.get(ref)
        if current is None or current.lifecycle is not PreparationLifecycle.REQUESTED:
            raise PreparationConflict("only a requested preparation can be dispatched")
        if updated_at < current.updated_at:
            raise PreparationConflict("dispatch timestamp cannot regress")
        result = self._session.execute(
            update(RuntimePreparationAttemptRow)
            .where(
                RuntimePreparationAttemptRow.preparation_id == str(ref),
                RuntimePreparationAttemptRow.lifecycle == PreparationLifecycle.REQUESTED.value,
                RuntimePreparationAttemptRow.revision == expected_revision,
            )
            .values(
                lifecycle=PreparationLifecycle.DISPATCHED.value,
                revision=expected_revision + 1,
                updated_at=updated_at,
            )
        )
        if getattr(result, "rowcount", None) != 1:
            raise PreparationConflict("stale preparation dispatch revision")
        loaded = self.get(ref)
        assert loaded is not None
        return loaded

    @staticmethod
    def _load(row: RuntimePreparationAttemptRow) -> PreparationAttempt:
        try:
            context = PreparationContext.model_validate(_json.validate_python(row.context_json))
            spec = (
                None
                if row.spec_json is None
                else RuntimePreparationSpec.model_validate(_json.validate_python(row.spec_json))
            )
            body = PreparationAttempt.model_validate(
                {
                    "preparation_ref": row.preparation_id,
                    "context": context,
                    "request_fingerprint": row.request_fingerprint,
                    "lifecycle": row.lifecycle,
                    "disposition": row.disposition,
                    "reason_code": row.reason_code,
                    "reserved_run_ref": row.reserved_run_id,
                    "spec": spec,
                    "permit_ref": row.permit_id,
                    "revision": row.revision,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                    "terminal_at": row.terminal_at,
                }
            )
            source = context.source
            if (
                body.request_fingerprint != canonical_digest(context)
                or str(context.request.mission_ref) != row.mission_id
                or str(context.request.plan_ref) != row.plan_id
                or context.plan_intent_sha256 != row.plan_intent_sha256
                or str(source.acquisition_ref) != row.acquisition_id
                or str(source.raw_artifact_ref) != row.raw_artifact_id
                or source.raw_sha256 != row.raw_sha256
                or str(source.manifest_artifact_ref) != row.manifest_artifact_id
                or source.manifest_sha256 != row.manifest_sha256
                or str(context.semantic_inspection_ref) != row.semantic_inspection_id
                or context.semantic_sha256 != row.semantic_sha256
                or str(context.classification_inspection_ref) != row.classification_inspection_id
                or context.classification_sha256 != row.classification_sha256
                or context.request.node_id != row.node_id
                or str(context.request.provider_id) != row.provider_id
                or context.provider_version != row.provider_version
                or (
                    None
                    if context.provider_availability is None
                    else context.provider_availability.value
                )
                != row.provider_availability
                or context.provider_node_lifecycle != row.provider_node_lifecycle
                or context.request.profile_id != row.profile_id
                or context.request.profile_version != row.profile_version
                or context.profile_sha256 != row.profile_sha256
                or (None if body.reserved_run_ref is None else str(body.reserved_run_ref))
                != row.reserved_run_id
                or (None if body.permit_ref is None else str(body.permit_ref)) != row.permit_id
                or context.validation_decision_ref
                != (None if row.validation_decision_id is None else row.validation_decision_id)
                or context.policy_decision_ref
                != (None if row.policy_decision_id is None else row.policy_decision_id)
                or context.policy_context_sha256 != row.policy_context_sha256
                or context.approval_decision_ref
                != (None if row.approval_decision_id is None else row.approval_decision_id)
            ):
                raise ValueError("preparation columns disagree with strict document")
            return body
        except (ValidationError, ValueError, TypeError):
            raise PreparationPersistenceError(
                "corrupt or unsupported preparation attempt"
            ) from None
