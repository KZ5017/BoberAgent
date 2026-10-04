"""E5-B metadata-only Resource ownership. No filesystem or runtime operations.

SQLite BEGIN IMMEDIATE serializes read/decide/write across repository instances. No
transaction survives a method call. A reservation is never a usable runtime lease.
"""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from math import ceil
from uuid import uuid4

from boberagent_contracts import (
    CapabilityRunStatus,
    DomainRef,
    PreparationAction,
    PreparationPermit,
    PreparationReasonCode,
    PythonProviderOperation,
    PythonProviderPhase,
    PythonResourceState,
    PythonRuntimeAuthorityProjection,
    PythonRuntimeFailure,
    PythonRuntimeReason,
    PythonRuntimeRequestBinding,
    PythonRuntimeValidity,
    ResourceRef,
    Sha256Digest,
    preparation_permit_digest,
    python_runtime_request_digest,
)
from boberagent_contracts.plan_canonical import canonical_value
from boberagent_contracts.python_runtime import RuntimeCorrelation
from boberagent_transport.preparation_materialization import MaterializationEvidence
from pydantic import TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..persistence.database import RuntimeDatabase
from ..persistence.orm import (
    ImportedArtifactRow,
    PreparationAuthorityRow,
    PreparationImportRow,
    PreparationMaterializationRow,
    PythonResourceBudgetRow,
    PythonResourceOperationRow,
    PythonResourceRow,
    RunRow,
    RuntimeResourceRow,
)
from .resource_models import (
    PEAK_CATEGORIES,
    BudgetAmount,
    BudgetBalance,
    BudgetCategory,
    CleanupState,
    OperationState,
    PythonResourceReservation,
    ResourceOperation,
)

_CORRELATION = TypeAdapter[RuntimeCorrelation](RuntimeCorrelation)
_ACTIONS = {
    PythonProviderOperation.INSPECT_INTERPRETER: PreparationAction.INSPECT_TRUSTED_INTERPRETER,
    PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT: PreparationAction.CREATE_EMPTY_PYTHON_ENVIRONMENT,
}


class ResourceOwnershipError(ValueError):
    def __init__(self, code: PreparationReasonCode, detail: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {detail}")


def _conflict(detail: str) -> ResourceOwnershipError:
    return ResourceOwnershipError(PreparationReasonCode.PREPARED_CONTENT_MISMATCH, detail)


def _interrupted() -> PythonRuntimeFailure:
    return PythonRuntimeFailure(
        reason_code=PreparationReasonCode.PREPARATION_INTERRUPTED,
        runtime_reason=PythonRuntimeReason.RUNTIME_QUARANTINED,
    )


class PythonResourceRepository:
    """Node-local bookkeeping API. There is deliberately no get_usable or READY setter."""

    def __init__(
        self,
        database: RuntimeDatabase,
        *,
        node_id: str,
        boot_generation: RuntimeCorrelation,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._database = database
        self._node_id = node_id
        self._boot = _CORRELATION.validate_python(boot_generation)
        self._clock = clock

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("Resource bookkeeping requires UTC time")
        return now

    @contextmanager
    def _write(self) -> Iterator[Session]:
        with self._database.transaction() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            yield session

    def reserve(
        self,
        authority: PythonRuntimeAuthorityProjection,
        *,
        principal_id: str,
    ) -> PythonResourceReservation:
        authority = PythonRuntimeAuthorityProjection.model_validate(authority.model_dump())
        binding = authority.binding
        digest = python_runtime_request_digest(binding)
        with self._write() as session:
            previous = session.scalar(
                select(PythonResourceRow).where(
                    (PythonResourceRow.request_sha256 == digest)
                    | (PythonResourceRow.preparation_id == str(binding.spec.preparation_ref))
                    | (PythonResourceRow.permit_id == str(binding.permit_ref))
                )
            )
            if previous is not None:
                if previous.request_sha256 != digest or canonical_value(
                    self._binding(previous)
                ) != canonical_value(binding):
                    raise _conflict("immutable reservation binding conflict")
                # Historical idempotent lookup is not fresh authority, even after expiry.
                self._admitted(session, authority.permit, principal_id)
                return self._snapshot(session, previous)
            self._admitted(session, authority.permit, principal_id)
            self._current(authority.permit, PreparationAction.CREATE_RUNTIME_RESOURCE)
            evidence = self._materialization(session, binding)
            baseline = self._baseline(session, authority.permit, evidence)
            ref = ResourceRef(f"resource-{uuid4()}")
            now = self._now()
            session.add(
                RuntimeResourceRow(
                    resource_id=str(ref),
                    resource_type="python_runtime",
                    provider="python-stdlib@1",
                    state=PythonResourceState.CREATING.value,
                    owner_ref=str(binding.spec.mission_ref),
                    created_by_run=str(binding.run_ref),
                    created_at=now,
                    updated_at=now,
                    last_activity_at=now,
                    access_modes_json=["EXCLUSIVE"],
                    expires_at=None,
                    lifecycle_metadata_json={"request_sha256": digest},
                )
            )
            session.flush()
            detail = PythonResourceRow(
                resource_id=str(ref),
                preparation_id=str(binding.spec.preparation_ref),
                permit_id=str(binding.permit_ref),
                request_sha256=digest,
                request_json=binding.model_dump(mode="json"),
                baseline_json=baseline,
                workspace_correlation=f"workspace-python-{uuid4()}",
                phase=PythonProviderPhase.RESERVED.value,
                validity=PythonRuntimeValidity.UNCHECKED.value,
                generation=0,
                active_operation_id=None,
                failure_json=None,
                cleanup_state=CleanupState.NONE.value,
            )
            session.add(detail)
            session.flush()
            return self._snapshot(session, detail)

    def load(self, ref: ResourceRef) -> PythonResourceReservation:
        with self._database.transaction() as session:
            return self._snapshot(session, self._detail(session, ref))

    def find_by_binding(self, digest: Sha256Digest) -> PythonResourceReservation | None:
        with self._database.transaction() as session:
            row = session.scalar(
                select(PythonResourceRow).where(PythonResourceRow.request_sha256 == digest)
            )
            return None if row is None else self._snapshot(session, row)

    def operations(self, ref: ResourceRef) -> tuple[ResourceOperation, ...]:
        with self._database.transaction() as session:
            self._detail(session, ref)
            return tuple(
                self._operation(row)
                for row in session.scalars(
                    select(PythonResourceOperationRow)
                    .where(PythonResourceOperationRow.resource_id == str(ref))
                    .order_by(PythonResourceOperationRow.generation)
                )
            )

    def claim(
        self,
        ref: ResourceRef,
        *,
        operation_id: RuntimeCorrelation,
        operation: PythonProviderOperation,
        owner_token: RuntimeCorrelation,
        lease_seconds: int = 60,
        principal_id: str | None = None,
    ) -> ResourceOperation:
        """RELEASE is Node-owned safety cleanup, not caller authority after permit expiry."""
        operation_id = _CORRELATION.validate_python(operation_id)
        owner_token = _CORRELATION.validate_python(owner_token)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("lease must be between 1 and 3600 seconds")
        operation = PythonProviderOperation(operation)
        with self._write() as session:
            detail = self._detail(session, ref)
            old = session.get(PythonResourceOperationRow, str(operation_id))
            if old is not None:
                if (old.resource_id, old.operation, old.owner_token, old.boot_generation) != (
                    str(ref),
                    operation.value,
                    str(owner_token),
                    str(self._boot),
                ) or old.expires_at - old.started_at != timedelta(seconds=lease_seconds):
                    raise _conflict("logical operation reused with different ownership/content")
                if old.state == OperationState.ACTIVE.value:
                    self._held(session, self._operation(old))
                return self._operation(old)
            if detail.active_operation_id is not None:
                raise ResourceOwnershipError(
                    PreparationReasonCode.RUNTIME_UNAVAILABLE,
                    "exclusive owner exists; reconcile, never steal",
                )
            resource = session.get(RuntimeResourceRow, str(ref))
            assert resource is not None
            if operation is PythonProviderOperation.RELEASE:
                if resource.state == PythonResourceState.CLOSED.value:
                    raise _conflict("closed Resource permits only identical cleanup replay")
            else:
                if resource.state != PythonResourceState.CREATING.value or detail.phase not in {
                    PythonProviderPhase.RESERVED.value,
                    PythonProviderPhase.BUILDING.value,
                }:
                    raise ResourceOwnershipError(
                        PreparationReasonCode.RUNTIME_UNAVAILABLE, "Resource unavailable"
                    )
                if operation not in _ACTIONS:
                    raise ResourceOwnershipError(
                        PreparationReasonCode.RUNTIME_UNAVAILABLE,
                        "runtime verification unavailable in E5-B",
                    )
                if principal_id is None:
                    raise ResourceOwnershipError(
                        PreparationReasonCode.PREPARATION_NOT_AUTHORIZED,
                        "admitted principal required",
                    )
                authority_row = session.get(PreparationAuthorityRow, detail.permit_id)
                assert authority_row is not None
                permit = PreparationPermit.model_validate(authority_row.permit_json)
                self._admitted(session, permit, principal_id)
                self._current(permit, _ACTIONS[operation])
                self._materialization(session, self._binding(detail))
            now = self._now()
            detail.generation += 1
            detail.active_operation_id = str(operation_id)
            row = PythonResourceOperationRow(
                operation_id=str(operation_id),
                resource_id=str(ref),
                operation=operation.value,
                owner_token=str(owner_token),
                boot_generation=str(self._boot),
                generation=detail.generation,
                state=OperationState.ACTIVE.value,
                started_at=now,
                expires_at=now + timedelta(seconds=lease_seconds),
                finished_at=None,
                failure_json=None,
            )
            session.add(row)
            session.flush()
            return self._operation(row)

    def mark_building(self, claim: ResourceOperation) -> PythonResourceReservation:
        with self._write() as session:
            detail, _row = self._held(session, claim)
            if claim.operation is not PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT:
                raise _conflict("BUILDING requires construction-owned operation metadata")
            detail.phase = PythonProviderPhase.BUILDING.value
            self._touch(session, detail)
            return self._snapshot(session, detail)

    def release_claim(self, claim: ResourceOperation) -> ResourceOperation:
        with self._write() as session:
            row = self._matching(session, claim)
            if row.state == OperationState.RELEASED.value:
                return self._operation(row)
            detail, row = self._held(session, claim)
            if claim.operation is PythonProviderOperation.RELEASE:
                raise _conflict("cleanup must be completed or failed explicitly")
            self._require_settled(session, row)
            self._finish(detail, row, OperationState.RELEASED)
            return self._operation(row)

    def reserve_budget(self, claim: ResourceOperation, amounts: tuple[BudgetAmount, ...]) -> None:
        values = self._amounts(amounts)
        with self._write() as session:
            row = self._matching(session, claim)
            existing = self._entries(session, row.operation_id)
            if existing:
                if {BudgetCategory(e.category): e.reserved for e in existing} != values:
                    raise _conflict("budget reservation replay changed")
                return
            detail, row = self._held(session, claim)
            balances = {balance.category: balance for balance in self._balances(session, detail)}
            for category, amount in values.items():
                balance = balances[category]
                if amount > balance.available:
                    raise ResourceOwnershipError(
                        PreparationReasonCode.WORKSPACE_LIMIT_EXCEEDED,
                        "preparation budget exhausted",
                    )
            for category, amount in values.items():
                session.add(
                    PythonResourceBudgetRow(
                        operation_id=row.operation_id,
                        category=category.value,
                        reserved=amount,
                        spent=None,
                    )
                )

    def settle_budget(self, claim: ResourceOperation, amounts: tuple[BudgetAmount, ...]) -> None:
        values = self._amounts(amounts)
        with self._write() as session:
            row = self._matching(session, claim)
            entries = self._entries(session, row.operation_id)
            if {BudgetCategory(e.category) for e in entries} != set(values):
                raise _conflict("settlement must cover exactly the reserved categories")
            if all(e.spent is not None for e in entries):
                if {BudgetCategory(e.category): e.spent for e in entries} != values:
                    raise _conflict("settled budget history cannot change")
                return
            self._held(session, claim)
            if any(values[BudgetCategory(e.category)] > e.reserved for e in entries):
                raise ResourceOwnershipError(
                    PreparationReasonCode.WORKSPACE_LIMIT_EXCEEDED, "settlement exceeds reservation"
                )
            for entry in entries:
                entry.spent = values[BudgetCategory(entry.category)]

    def budget(self, ref: ResourceRef) -> tuple[BudgetBalance, ...]:
        with self._database.transaction() as session:
            return self._balances(session, self._detail(session, ref))

    def remaining_operation_seconds(self, claim: ResourceOperation) -> int:
        """Read-only E5-C deadline bound; it never extends ownership/authority."""
        with self._database.transaction() as session:
            detail, _row = self._held(session, claim)
            authority = session.get(PreparationAuthorityRow, detail.permit_id)
            assert authority is not None
            permit = PreparationPermit.model_validate(authority.permit_json)
            return max(
                0, int((min(claim.expires_at, permit.expires_at) - self._now()).total_seconds())
            )

    def quarantine(
        self, ref: ResourceRef, failure: PythonRuntimeFailure
    ) -> PythonResourceReservation:
        """Node-owned safety operation; invalidates any old owner, never returns authority."""
        failure = PythonRuntimeFailure.model_validate(failure.model_dump())
        with self._write() as session:
            detail = self._detail(session, ref)
            if detail.phase != PythonProviderPhase.REMOVED.value:
                self._quarantine(session, detail, failure)
            return self._snapshot(session, detail)

    def begin_cleanup(self, claim: ResourceOperation) -> PythonResourceReservation:
        with self._write() as session:
            detail, _row = self._held(session, claim)
            if claim.operation is not PythonProviderOperation.RELEASE:
                raise _conflict("cleanup requires exclusive RELEASE ownership")
            resource = session.get(RuntimeResourceRow, detail.resource_id)
            assert resource is not None
            resource.state = PythonResourceState.CLOSING.value
            detail.cleanup_state = CleanupState.PENDING.value
            self._touch(session, detail)
            return self._snapshot(session, detail)

    def complete_cleanup(self, claim: ResourceOperation) -> PythonResourceReservation:
        """Metadata-only completion: there are no E5-B runtime files to remove."""
        with self._write() as session:
            row = self._matching(session, claim)
            detail = self._detail(session, claim.resource_ref)
            if (
                row.state == OperationState.COMPLETED.value
                and detail.cleanup_state == CleanupState.COMPLETED.value
            ):
                return self._snapshot(session, detail)
            detail, row = self._held(session, claim)
            if (
                claim.operation is not PythonProviderOperation.RELEASE
                or detail.cleanup_state != CleanupState.PENDING.value
            ):
                raise _conflict("cleanup was not started")
            self._require_settled(session, row)
            resource = session.get(RuntimeResourceRow, detail.resource_id)
            assert resource is not None
            resource.state = PythonResourceState.CLOSED.value
            detail.phase = PythonProviderPhase.REMOVED.value
            detail.cleanup_state = CleanupState.COMPLETED.value
            self._finish(detail, row, OperationState.COMPLETED)
            self._touch(session, detail)
            return self._snapshot(session, detail)

    def fail_cleanup(
        self, claim: ResourceOperation, failure: PythonRuntimeFailure
    ) -> PythonResourceReservation:
        failure = PythonRuntimeFailure.model_validate(failure.model_dump())
        with self._write() as session:
            detail, row = self._held(session, claim)
            if (
                claim.operation is not PythonProviderOperation.RELEASE
                or detail.cleanup_state != CleanupState.PENDING.value
            ):
                raise _conflict("cleanup failure requires RELEASE ownership")
            self._quarantine(session, detail, failure)
            row.state = OperationState.FAILED.value
            detail.cleanup_state = CleanupState.FAILED.value
            return self._snapshot(session, detail)

    def reconcile(self) -> int:
        """Metadata only. RESERVED without ownership stays RESERVED. Never rebuild."""
        count = 0
        with self._write() as session:
            for detail in session.scalars(select(PythonResourceRow)):
                row = (
                    session.get(PythonResourceOperationRow, detail.active_operation_id)
                    if detail.active_operation_id
                    else None
                )
                abandoned = row is not None and (
                    row.boot_generation != str(self._boot) or row.expires_at <= self._now()
                )
                orphaned = row is None and detail.phase == PythonProviderPhase.BUILDING.value
                if abandoned or orphaned:
                    self._quarantine(session, detail, _interrupted())
                    if detail.cleanup_state == CleanupState.PENDING.value:
                        detail.cleanup_state = CleanupState.FAILED.value
                    count += 1
        return count

    def _admitted(self, session: Session, permit: PreparationPermit, principal: str) -> None:
        row = session.get(PreparationAuthorityRow, str(permit.permit_ref))
        run = session.get(RunRow, str(permit.run_ref))
        if (
            row is None
            or row.principal_id != principal
            or row.authority_sha256 != preparation_permit_digest(permit)
            or canonical_value(PreparationPermit.model_validate(row.permit_json))
            != canonical_value(permit)
            or run is None
            or run.mission_id != str(permit.spec.mission_ref)
            or row.run_id != str(permit.run_ref)
            or row.preparation_id != str(permit.spec.preparation_ref)
            or permit.spec.node_id != self._node_id
        ):
            raise ResourceOwnershipError(
                PreparationReasonCode.PREPARATION_NOT_AUTHORIZED,
                "exact admitted authority required",
            )
        if run.status != CapabilityRunStatus.QUEUED.value:
            raise ResourceOwnershipError(
                PreparationReasonCode.AUTHORITY_STALE, "preparation Run is not pending"
            )

    def _current(self, permit: PreparationPermit, action: PreparationAction) -> None:
        if not permit.not_before <= self._now() < permit.expires_at:
            raise ResourceOwnershipError(
                PreparationReasonCode.AUTHORITY_STALE, "permit expired or not active"
            )
        if action not in permit.spec.allowed_actions:
            raise ResourceOwnershipError(
                PreparationReasonCode.PREPARATION_NOT_AUTHORIZED, "preparation action not granted"
            )

    def _materialization(
        self, session: Session, binding: PythonRuntimeRequestBinding
    ) -> MaterializationEvidence:
        row = session.get(PreparationMaterializationRow, str(binding.spec.preparation_ref))
        if row is None or row.state != "PUBLISHED" or row.evidence_json is None:
            raise _conflict("published E4 metadata required")
        evidence = MaterializationEvidence.model_validate(row.evidence_json)
        source = binding.spec.source.plan_source
        if (
            row.permit_id != str(binding.permit_ref)
            or row.run_id != str(binding.run_ref)
            or row.materialization_id != str(binding.materialization_id)
            or evidence.materialization_id != binding.materialization_id
            or evidence.tree_sha256 != binding.source_tree_sha256
            or evidence.node_id != self._node_id
            or evidence.preparation_ref != binding.spec.preparation_ref
            or evidence.permit_ref != binding.permit_ref
            or evidence.permit_sha256 != binding.permit_sha256
            or evidence.run_ref != binding.run_ref
            or evidence.mission_ref != binding.spec.mission_ref
            or evidence.plan_ref != binding.spec.plan_ref
            or evidence.plan_intent_sha256 != binding.spec.plan_intent_sha256
            or evidence.raw_artifact_ref != source.raw_artifact_ref
            or evidence.raw_sha256 != source.raw_sha256
            or evidence.manifest_artifact_ref != source.manifest_artifact_ref
            or evidence.manifest_sha256 != source.manifest_sha256
            or evidence.budgets != binding.spec.budgets
        ):
            raise _conflict("E4 materialization binding mismatch")
        for ref, digest, size in (
            (source.raw_artifact_ref, source.raw_sha256, source.raw_size_bytes),
            (
                source.manifest_artifact_ref,
                source.manifest_sha256,
                binding.spec.source.manifest_size_bytes,
            ),
        ):
            imported = session.get(ImportedArtifactRow, str(ref))
            if imported is None or imported.sha256 != digest or imported.size_bytes != size:
                raise _conflict("exact verified E3 import metadata required")
        return evidence

    @staticmethod
    def _baseline(
        session: Session, permit: PreparationPermit, evidence: MaterializationEvidence
    ) -> dict[str, int]:
        budgets = permit.spec.budgets
        imports = tuple(
            session.scalars(
                select(PreparationImportRow).where(
                    PreparationImportRow.permit_id == str(permit.permit_ref),
                )
            )
        )
        # Retain elapsed import accounting too: retries/reconnect must not reset it.
        # Wall-clock intervals are conservative bookkeeping, not monotonic host proof.
        if any(row.state != "VERIFIED" or row.updated_at < row.started_at for row in imports):
            raise _conflict("incomplete or inconsistent E3 import accounting")
        import_seconds = sum(
            ceil((row.updated_at - row.started_at).total_seconds()) for row in imports
        )
        values = {
            BudgetCategory.IMPORTED_BYTES.value: permit.spec.source.plan_source.raw_size_bytes
            + permit.spec.source.manifest_size_bytes,
            BudgetCategory.MATERIALIZED_BYTES.value: evidence.materialized_bytes,
            BudgetCategory.FILE_COUNT.value: evidence.file_count,
            BudgetCategory.TEMPORARY_BYTES.value: evidence.observed_temporary_bytes,
            BudgetCategory.WRITE_BYTES.value: evidence.observed_write_bytes
            + permit.spec.source.plan_source.raw_size_bytes
            + permit.spec.source.manifest_size_bytes,
            BudgetCategory.TOTAL_SECONDS.value: import_seconds
            + ceil(evidence.observed_duration_seconds),
            # E4 did not retain a measured maximum depth. Charge its admitted ceiling,
            # not a fabricated measured zero. This is accounting, not enforcement proof.
            BudgetCategory.PATH_DEPTH.value: budgets.max_path_depth,
        }
        if any(value > getattr(budgets, key) for key, value in values.items()):
            raise ResourceOwnershipError(
                PreparationReasonCode.WORKSPACE_LIMIT_EXCEEDED,
                "retained E3/E4 usage exceeds budget",
            )
        return values

    @staticmethod
    def _binding(row: PythonResourceRow) -> PythonRuntimeRequestBinding:
        binding = PythonRuntimeRequestBinding.model_validate(row.request_json)
        if python_runtime_request_digest(binding) != row.request_sha256:
            raise _conflict("stored immutable binding digest mismatch")
        return binding

    @staticmethod
    def _detail(session: Session, ref: ResourceRef) -> PythonResourceRow:
        row = session.get(PythonResourceRow, str(ref))
        if row is None:
            raise KeyError(f"unknown Python Resource: {ref}")
        return row

    def _snapshot(self, session: Session, detail: PythonResourceRow) -> PythonResourceReservation:
        resource = session.get(RuntimeResourceRow, detail.resource_id)
        assert resource is not None
        return PythonResourceReservation(
            resource_ref=ResourceRef(detail.resource_id),
            request=self._binding(detail),
            request_sha256=detail.request_sha256,
            workspace_correlation=DomainRef(detail.workspace_correlation),
            state=PythonResourceState(resource.state),
            phase=PythonProviderPhase(detail.phase),
            validity=PythonRuntimeValidity(detail.validity),
            generation=detail.generation,
            active_operation_id=None
            if detail.active_operation_id is None
            else DomainRef(detail.active_operation_id),
            cleanup=CleanupState(detail.cleanup_state),
            failure=None
            if detail.failure_json is None
            else PythonRuntimeFailure.model_validate_json(json.dumps(detail.failure_json)),
            created_at=resource.created_at,
            updated_at=resource.updated_at,
        )

    @staticmethod
    def _operation(row: PythonResourceOperationRow) -> ResourceOperation:
        return ResourceOperation(
            resource_ref=ResourceRef(row.resource_id),
            operation_id=DomainRef(row.operation_id),
            operation=PythonProviderOperation(row.operation),
            owner_token=DomainRef(row.owner_token),
            boot_generation=DomainRef(row.boot_generation),
            generation=row.generation,
            state=OperationState(row.state),
            started_at=row.started_at,
            expires_at=row.expires_at,
            finished_at=row.finished_at,
            failure=None
            if row.failure_json is None
            else PythonRuntimeFailure.model_validate_json(json.dumps(row.failure_json)),
        )

    def _matching(self, session: Session, claim: ResourceOperation) -> PythonResourceOperationRow:
        row = session.get(PythonResourceOperationRow, str(claim.operation_id))
        if row is None or (
            row.resource_id,
            row.owner_token,
            row.boot_generation,
            row.generation,
            row.operation,
        ) != (
            str(claim.resource_ref),
            str(claim.owner_token),
            str(claim.boot_generation),
            claim.generation,
            claim.operation.value,
        ):
            raise _conflict("operation ownership/generation mismatch")
        return row

    def _held(
        self, session: Session, claim: ResourceOperation
    ) -> tuple[PythonResourceRow, PythonResourceOperationRow]:
        row = self._matching(session, claim)
        detail = self._detail(session, claim.resource_ref)
        if (
            row.state != OperationState.ACTIVE.value
            or detail.active_operation_id != row.operation_id
            or row.boot_generation != str(self._boot)
            or row.expires_at <= self._now()
        ):
            raise ResourceOwnershipError(
                PreparationReasonCode.PREPARATION_INTERRUPTED,
                "stale or inactive exclusive ownership",
            )
        if claim.operation is not PythonProviderOperation.RELEASE:
            authority = session.get(PreparationAuthorityRow, detail.permit_id)
            assert authority is not None
            permit = PreparationPermit.model_validate(authority.permit_json)
            self._admitted(session, permit, authority.principal_id)
            self._current(permit, _ACTIONS[claim.operation])
            self._materialization(session, self._binding(detail))
        return detail, row

    @staticmethod
    def _amounts(amounts: tuple[BudgetAmount, ...]) -> dict[BudgetCategory, int]:
        values = [BudgetAmount.model_validate(amount.model_dump()) for amount in amounts]
        result = {amount.category: amount.amount for amount in values}
        if not result or len(result) != len(values):
            raise ValueError("nonempty unique budget categories required")
        return result

    @staticmethod
    def _entries(session: Session, operation_id: str) -> list[PythonResourceBudgetRow]:
        return list(
            session.scalars(
                select(PythonResourceBudgetRow).where(
                    PythonResourceBudgetRow.operation_id == operation_id
                )
            )
        )

    def _balances(self, session: Session, detail: PythonResourceRow) -> tuple[BudgetBalance, ...]:
        binding = self._binding(detail)
        entries = list(
            session.scalars(
                select(PythonResourceBudgetRow)
                .join(PythonResourceOperationRow)
                .where(PythonResourceOperationRow.resource_id == detail.resource_id)
            )
        )
        result = []
        for category in BudgetCategory:
            selected = [row for row in entries if row.category == category.value]
            baseline = detail.baseline_json.get(category.value, 0)
            assert type(baseline) is int
            committed = [baseline, *(row.spent for row in selected if row.spent is not None)]
            held = sum(row.reserved for row in selected if row.spent is None)
            used = max(committed) if category in PEAK_CATEGORIES else sum(committed)
            limit = getattr(binding.spec.budgets, category.value)
            # Peak reservations are ceilings for the next exclusive operation; historic
            # maxima remain retained but do not consume a second concurrent allocation.
            available = limit - held if category in PEAK_CATEGORIES else limit - used - held
            result.append(
                BudgetBalance(
                    category=category, limit=limit, committed=used, held=held, available=available
                )
            )
        return tuple(result)

    def _require_settled(self, session: Session, row: PythonResourceOperationRow) -> None:
        if any(entry.spent is None for entry in self._entries(session, row.operation_id)):
            raise _conflict("unsettled reservation requires conservative quarantine, not refund")

    def _finish(
        self, detail: PythonResourceRow, row: PythonResourceOperationRow, state: OperationState
    ) -> None:
        row.state = state.value
        row.finished_at = self._now()
        detail.active_operation_id = None

    def _touch(self, session: Session, detail: PythonResourceRow) -> None:
        resource = session.get(RuntimeResourceRow, detail.resource_id)
        assert resource is not None
        resource.updated_at = self._now()
        resource.last_activity_at = resource.updated_at

    def _quarantine(
        self, session: Session, detail: PythonResourceRow, failure: PythonRuntimeFailure
    ) -> None:
        if detail.active_operation_id is not None:
            row = session.get(PythonResourceOperationRow, detail.active_operation_id)
            assert row is not None
            for entry in self._entries(session, row.operation_id):
                if entry.spent is None:
                    entry.spent = entry.reserved  # no refund for interrupted/unknown work
            row.failure_json = failure.model_dump(mode="json")
            self._finish(detail, row, OperationState.INTERRUPTED)
        resource = session.get(RuntimeResourceRow, detail.resource_id)
        assert resource is not None
        if resource.state != PythonResourceState.CLOSING.value:
            resource.state = PythonResourceState.LOST.value
        detail.phase = PythonProviderPhase.QUARANTINED.value
        if detail.failure_json is None:
            detail.failure_json = failure.model_dump(mode="json")
        self._touch(session, detail)
