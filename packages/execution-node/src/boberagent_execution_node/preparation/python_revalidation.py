"""E5-F exact retained-runtime validation. No constructor, executor or E6 result.

One held, budgeted operation owns all active work. READY is only a current-boot
projection backed by immutable proof, never execution authorization.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from math import ceil

from boberagent_contracts import (
    CapabilityRunStatus,
    ConfinementFeature,
    DomainRef,
    PreparationAction,
    PreparationPermit,
    PreparationReasonCode,
    PreparationUsage,
    PythonProviderOperation,
    PythonRuntimeCurrentState,
    PythonRuntimeEvidence,
    PythonRuntimeFailure,
    PythonRuntimeNonActions,
    PythonRuntimeOutputEvidence,
    PythonRuntimeReason,
    Sha256Digest,
    python_runtime_binding_digest,
    python_runtime_evidence_digest,
)
from boberagent_contracts.python_runtime import RuntimeResourceRef
from boberagent_sdk.exceptions import ExecutionCancelled
from boberagent_sdk.services.artifacts import ArtifactService
from boberagent_sdk.services.cancellation import CancellationService
from sqlalchemy import select

from ..persistence.orm import (
    PreparationAuthorityRow,
    PythonResourceOperationRow,
    PythonRevalidationRow,
    RuntimeResourceRow,
)
from .environment_models import WRITE_LIMIT, EnvironmentIdentity
from .python_distribution import digest_value, inventory
from .python_environment import (
    _CONTROL_WRITE_BYTES,
    EnvironmentFailure,
    PythonEnvironmentProvider,
    _environment_distribution,
    _operation_id,
)
from .python_provenance import enforcement
from .resource_models import BudgetAmount, BudgetCategory, OperationState, ResourceOperation
from .resources import ResourceOwnershipError
from .runtime_confinement_models import (
    ConfinementCheck,
    EnvironmentLimits,
    ProbeEvidence,
    Record,
    TrustedPythonOperation,
)


class RevalidationProof(Record):
    construction_sha256: Sha256Digest
    check: ConfinementCheck
    verification: ProbeEvidence


_FIELDS = {
    BudgetCategory.IMPORTED_BYTES: "imported_bytes",
    BudgetCategory.MATERIALIZED_BYTES: "materialized_bytes",
    BudgetCategory.FILE_COUNT: "file_count",
    BudgetCategory.TEMPORARY_BYTES: "temporary_bytes",
    BudgetCategory.WRITE_BYTES: "preparation_write_bytes",
    BudgetCategory.PROCESSES: "peak_processes",
    BudgetCategory.MEMORY_BYTES: "peak_memory_bytes",
    BudgetCategory.PROCESS_SECONDS: "process_runtime_seconds",
    BudgetCategory.TOTAL_SECONDS: "total_runtime_seconds",
    BudgetCategory.OUTPUT_BYTES: "captured_output_bytes",
}


class PythonRevalidationRepository:
    def __init__(self, provider: PythonEnvironmentProvider) -> None:
        self.provider = provider
        self.resources = provider.repository.resources

    def history(self, ref: RuntimeResourceRef) -> tuple[PythonRuntimeEvidence, ...]:
        with self.resources._database.transaction() as session:
            rows = session.scalars(
                select(PythonRevalidationRow)
                .join(
                    PythonResourceOperationRow,
                    PythonResourceOperationRow.operation_id == PythonRevalidationRow.operation_id,
                )
                .where(PythonRevalidationRow.resource_id == str(ref))
                .order_by(PythonResourceOperationRow.generation)
            )
            results = []
            for row in rows:
                evidence = PythonRuntimeEvidence.model_validate_json(json.dumps(row.evidence_json))
                proof = RevalidationProof.model_validate(row.proof_json)
                if (
                    python_runtime_evidence_digest(evidence) != row.evidence_sha256
                    or evidence.binding.resource_ref != ref
                    or str(evidence.budget_ledger_correlation) != row.operation_id
                    or evidence.enforcement != enforcement(proof.check, proof.verification)
                    or proof.construction_sha256
                    != digest_value(self.provider.repository.history(ref))
                    or hashlib.sha256(bytes.fromhex(proof.verification.stdout_hex)).hexdigest()
                    != evidence.outputs.stdout_sha256
                ):
                    raise EnvironmentFailure()
                results.append(evidence)
            return tuple(results)

    def current(
        self,
        ref: RuntimeResourceRef,
        *,
        run_status: CapabilityRunStatus = CapabilityRunStatus.QUEUED,
    ) -> PythonRuntimeCurrentState:
        retained = self.provider.repository.inspect_retained(ref)
        with self.resources._database.transaction() as session:
            detail = self.resources._detail(session, ref)
            snapshot = self.resources._snapshot(session, detail)
            if snapshot.validity.value == "VALID":
                authority = session.get(PreparationAuthorityRow, detail.permit_id)
                assert authority is not None
                permit = PreparationPermit.model_validate(authority.permit_json)
                self.resources._admitted(
                    session, permit, authority.principal_id, run_status=run_status
                )
                self.resources._current(permit, PreparationAction.VERIFY_PYTHON_ENVIRONMENT)
                if detail.checked_boot != str(self.resources._boot):
                    raise EnvironmentFailure(PythonRuntimeReason.PYTHON_RUNTIME_UNAVAILABLE)
                try:
                    if (
                        _environment_distribution(self.provider.distribution).identity()
                        != retained.binding.interpreter.distribution
                        or self.provider.backend_identity != retained.binding.backend
                        or self.provider.helper_sha256 != retained.helper_sha256
                    ):
                        raise EnvironmentFailure()
                except (ValueError, OSError, RuntimeError):
                    # Status may detect drift, but cannot run probes or renew readiness.
                    # Roll back this read transaction before the safety write.
                    session.rollback()
                    self.resources.quarantine(ref, EnvironmentFailure().failure)
                    raise EnvironmentFailure() from None
            return PythonRuntimeCurrentState(
                resource_ref=ref,
                binding_sha256=python_runtime_binding_digest(retained.binding),
                state=snapshot.state,
                phase=snapshot.phase,
                validity=snapshot.validity,
                checked_at=detail.checked_at,
                boot_generation=None
                if detail.checked_boot is None
                else DomainRef(detail.checked_boot),
                failure=snapshot.failure,
            )

    def complete(
        self, claim: ResourceOperation, evidence: PythonRuntimeEvidence, proof: RevalidationProof
    ) -> None:
        evidence = PythonRuntimeEvidence.model_validate_json(evidence.model_dump_json())
        with self.resources._write() as session:
            detail, operation = self.resources._held(session, claim)
            self.resources._require_settled(session, operation)
            if (
                claim.operation is not PythonProviderOperation.REVALIDATE
                or evidence.budget_ledger_correlation != claim.operation_id
                or evidence.binding.request != self.resources._binding(detail)
                or evidence.binding.resource_ref != claim.resource_ref
                or evidence.verification != "VERIFIED"
                or not evidence.evidence_artifact_refs
            ):
                raise EnvironmentFailure()
            session.add(
                PythonRevalidationRow(
                    operation_id=str(claim.operation_id),
                    resource_id=str(claim.resource_ref),
                    evidence_sha256=python_runtime_evidence_digest(evidence),
                    evidence_json=evidence.model_dump(mode="json"),
                    proof_json=proof.model_dump(mode="json"),
                )
            )
            self.resources._finish(detail, operation, OperationState.COMPLETED)
            session.flush()  # The availability guards require the durable proof and completed owner.
            detail.verification_id = str(claim.operation_id)
            detail.checked_at = self.resources._now()
            detail.checked_boot = str(claim.boot_generation)
            detail.phase = "PUBLISHED"
            detail.validity = "VALID"
            session.flush()
            resource = session.get(RuntimeResourceRow, str(claim.resource_ref))
            assert resource is not None
            resource.state = "READY"
            resource.updated_at = self.resources._now()


async def revalidate_environment(
    repository: PythonRevalidationRepository,
    claim: ResourceOperation,
    *,
    verify_source: Callable[[], None],
    artifacts: ArtifactService,
    cancellation: CancellationService | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PythonRuntimeEvidence:
    """Only fixed verification code runs, with source absent from its namespace."""
    provider, resources = repository.provider, repository.resources
    if claim.operation is not PythonProviderOperation.REVALIDATE:
        raise ValueError("exclusive revalidation required")
    with resources._database.transaction() as session:
        resources._matching(session, claim)  # Forged callers cannot poison another Resource.
    for prior in repository.history(claim.resource_ref):
        if prior.budget_ledger_correlation == claim.operation_id:
            repository.current(claim.resource_ref)  # Passive integrity, never promotion on replay.
            return prior
    started, monotonic = clock(), time.monotonic()
    # Conservative control/verification capacity, including hashing/publication evidence.
    # WRITE_LIMIT is a charged upper allowance, not a claim to rewrite the retained venv.
    amounts = {
        BudgetCategory.TEMPORARY_BYTES: 160 * 1024**2,
        BudgetCategory.WRITE_BYTES: _CONTROL_WRITE_BYTES + WRITE_LIMIT + 262144,
        # Thirteen controls plus ONE verifier descriptor/scaffold allowance.
        # Construction's two environment operations are not repeated here.
        BudgetCategory.FILE_COUNT: 13 * 65 + 2050 + 8,
        BudgetCategory.PATH_DEPTH: 4,
        BudgetCategory.PROCESSES: 11,
        BudgetCategory.MEMORY_BYTES: 520 * 1024**2,
        BudgetCategory.PROCESS_SECONDS: 38,
        BudgetCategory.TOTAL_SECONDS: 250,
        BudgetCategory.OUTPUT_BYTES: 14 * 4096,
    }
    try:
        if resources.remaining_operation_seconds(claim) < 250:
            raise EnvironmentFailure(PythonRuntimeReason.RUNTIME_LIMIT_UNAVAILABLE)
        resources.reserve_budget(
            claim, tuple(BudgetAmount(category=k, amount=v) for k, v in amounts.items())
        )
        async with asyncio.timeout(245):
            retained = provider.repository.inspect_retained(claim.resource_ref)
            verify_source()
            manifest = _environment_distribution(provider.distribution)
            if (
                manifest.identity() != retained.binding.interpreter.distribution
                or provider.backend_identity != retained.binding.backend
                or provider.helper_sha256 != retained.helper_sha256
            ):
                raise EnvironmentFailure()
            if cancellation is not None:
                await cancellation.checkpoint()
            check = await provider.backend.check(tuple(ConfinementFeature))
            probe = await provider.backend.run_environment_verify(
                provider.distribution,
                _operation_id(claim, "revalidate"),
                provider.repository.storage.resource_directory(claim.resource_ref) / "venv",
                provider.helper_sha256,
                cancellation=cancellation,
            )
            proof = enforcement(check, probe)
            if (
                probe.probe is not TrustedPythonOperation.VERIFY_ENVIRONMENT
                or probe.limits != EnvironmentLimits()
                or not probe.passed
                or not probe.attached_before_exec
                or not probe.group_empty
                or probe.exit_code != 0
                or probe.stderr_hex
                or probe.pids_events
                or probe.oom_events
                or probe.helper_sha256 != retained.binding.backend.helper_sha256
                or probe.bubblewrap_sha256 != retained.binding.backend.binary_sha256
                or probe.memory_peak > probe.limits.memory_bytes
                or probe.duration_milliseconds > probe.limits.seconds * 1000
                or probe.boot_generation != claim.boot_generation
            ):
                raise EnvironmentFailure(PythonRuntimeReason.RUNTIME_REVALIDATION_FAILED)
            identity = EnvironmentIdentity.model_validate_json(bytes.fromhex(probe.stdout_hex))
            old_identity = EnvironmentIdentity.model_validate_json(
                bytes.fromhex(retained.verification.stdout_hex)
            )
            if identity != old_identity:
                raise EnvironmentFailure()
            verify_source()
            if (
                inventory(provider.distribution) != manifest
                or provider.repository.inspect_retained(claim.resource_ref) != retained
            ):
                raise EnvironmentFailure()
            if cancellation is not None:
                await cancellation.checkpoint()
            settled = dict(amounts)
            elapsed = ceil((time.monotonic() - monotonic) * 1000)
            settled[BudgetCategory.TOTAL_SECONDS] = ceil(elapsed / 1000)
            settled[BudgetCategory.OUTPUT_BYTES] = sum(
                (len(p.stdout_hex) + len(p.stderr_hex)) // 2 for p in (*check.probes, probe)
            )
            resources.settle_budget(
                claim, tuple(BudgetAmount(category=k, amount=v) for k, v in settled.items())
            )
            balances = {b.category: b.committed for b in resources.budget(claim.resource_ref)}
            evidence = PythonRuntimeEvidence(
                schema_version="PythonRuntimeEvidence-v1",
                binding=retained.binding,
                workspace_correlation=resources.load(claim.resource_ref).workspace_correlation,
                operation=claim.operation,
                environment=retained.environment,
                non_actions=PythonRuntimeNonActions(
                    source_imported=False,
                    source_compiled=False,
                    entrypoint_executed=False,
                    package_installed=False,
                    activation_script_sourced=False,
                    preparation_network="NONE",
                ),
                enforcement=proof,
                aggregate_usage=PreparationUsage(
                    **{field: balances[key] for key, field in _FIELDS.items()}
                ),
                e5_usage=PreparationUsage(
                    **{field: settled.get(key, 0) for key, field in _FIELDS.items()}
                ),
                budget_ledger_correlation=claim.operation_id,
                outputs=PythonRuntimeOutputEvidence(
                    stdout_bytes=len(probe.stdout_hex) // 2,
                    stdout_sha256=hashlib.sha256(bytes.fromhex(probe.stdout_hex)).hexdigest(),
                    stderr_bytes=len(probe.stderr_hex) // 2,
                    stderr_sha256=hashlib.sha256(bytes.fromhex(probe.stderr_hex)).hexdigest(),
                ),
                started_at=started,
                completed_at=clock(),
                monotonic_duration_milliseconds=elapsed,
                verification="VERIFIED",
                failure=None,
                evidence_artifact_refs=(),
            )
            private_proof = RevalidationProof(
                construction_sha256=digest_value(retained),
                check=check,
                verification=probe,
            )
            payload = evidence.model_dump_json().encode()
            if len(payload) > 65536 or len(private_proof.model_dump_json().encode()) > 262144:
                raise EnvironmentFailure()
            artifact = await artifacts.create_from_bytes(
                artifact_type="python.runtime.revalidation",
                data=payload,
                media_type="application/json",
            )
            evidence = PythonRuntimeEvidence.model_validate(
                evidence.model_copy(
                    update={"evidence_artifact_refs": (artifact.artifact_id,)}
                ).model_dump()
            )
            repository.complete(claim, evidence, private_proof)
            return evidence
    except BaseException as error:
        failure = getattr(error, "failure", None)
        if not isinstance(failure, PythonRuntimeFailure):
            failure = (
                EnvironmentFailure(PythonRuntimeReason.RUNTIME_LIMIT_UNAVAILABLE).failure
                if isinstance(error, TimeoutError)
                else EnvironmentFailure().failure
                if isinstance(error, (ValueError, OSError))
                and not isinstance(error, ResourceOwnershipError)
                else PythonRuntimeFailure(
                    reason_code=error.code
                    if isinstance(error, ResourceOwnershipError)
                    else PreparationReasonCode.PREPARATION_CANCELLED
                    if isinstance(error, (asyncio.CancelledError, ExecutionCancelled))
                    else PreparationReasonCode.PREPARATION_INTERRUPTED,
                )
            )
        resources.quarantine(claim.resource_ref, failure)
        if isinstance(error, asyncio.CancelledError):
            raise
        raise EnvironmentFailure(
            failure.runtime_reason or PythonRuntimeReason.RUNTIME_REVALIDATION_FAILED
        ) from None
