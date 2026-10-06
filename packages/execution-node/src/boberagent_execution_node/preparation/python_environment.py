"""E5-E closed construction, bounded publication, immutable pre-F evidence.

No SDK/transport wiring, READY/current VALID promotion, source access or executor.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from typing import Protocol

from boberagent_contracts import (
    ConfinementFeature,
    DomainRef,
    PreparationReasonCode,
    PythonBackendIdentity,
    PythonProviderOperation,
    PythonRuntimeFailure,
    PythonRuntimeReason,
    python_runtime_binding_digest,
)
from boberagent_contracts.python_runtime import RuntimeCorrelation, RuntimeResourceRef
from boberagent_sdk.services.cancellation import CancellationService
from pydantic import Field, StrictInt
from sqlalchemy import select

from ..persistence.orm import PythonEnvironmentRow, WorkspaceRow
from .environment_models import (
    EXPORT_LIMIT,
    FILE_LIMIT,
    WRITE_LIMIT,
    EmptyEnvironmentEvidence,
    EnvironmentIdentity,
)
from .environment_storage import EnvironmentStorage
from .python_distribution import (
    ProjectedDistributionManifest,
    PythonDistributionConfiguration,
    digest_value,
    inventory,
)
from .python_provenance import PythonProvenanceRepository, enforcement
from .resource_models import BudgetAmount, BudgetCategory, OperationState, ResourceOperation
from .resources import PythonResourceRepository, ResourceOwnershipError
from .runtime_confinement import RuntimeConfinementUnavailable
from .runtime_confinement_models import ConfinementCheck, ProbeEvidence, Record


class EnvironmentFailure(RuntimeError):
    def __init__(
        self, reason: PythonRuntimeReason = PythonRuntimeReason.RUNTIME_INTEGRITY_FAILURE
    ) -> None:
        self.failure = PythonRuntimeFailure(
            reason_code=reason.preparation_reason, runtime_reason=reason
        )
        super().__init__(reason.value)


class ConstructionInProgress(ResourceOwnershipError):
    def __init__(self) -> None:
        super().__init__(PreparationReasonCode.RUNTIME_UNAVAILABLE, "construction already owned")


def _environment_distribution(
    configuration: PythonDistributionConfiguration,
) -> ProjectedDistributionManifest:
    """E's site-enabled verifier has a stricter admission than D's -S identity.

    Reject startup customization; never filter or repin D's certified view.
    The venv's separate closed inventory excludes all hooks/packages there.
    """
    manifest = inventory(configuration)
    if not isinstance(
        manifest, ProjectedDistributionManifest
    ) or manifest.projection.profile.unsupported_optional != ("TKINTER_TCL_TK", "PACKAGE_MANAGER"):
        raise EnvironmentFailure()
    for entry in manifest.entries:
        for root in ("lib/python3.12/", "lib/python3.12/lib-dynload/"):
            if not entry.path.startswith(root):
                continue
            relative = entry.path[len(root) :]
            if relative.startswith("__pycache__/"):
                relative = relative.removeprefix("__pycache__/")
            module = relative.split("/")[0]
            if any(
                module == name or module.startswith(name + ".")
                for name in ("sitecustomize", "usercustomize")
            ) or ("/" not in relative and relative.endswith(".pth")):
                raise EnvironmentFailure()
    return manifest


class ConstructionSummary(Record):
    written_bytes: StrictInt = Field(ge=0, le=WRITE_LIMIT)
    created_entries: StrictInt = Field(ge=0, le=FILE_LIMIT)
    export_bytes: StrictInt = Field(ge=4, le=EXPORT_LIMIT)


class EnvironmentBackend(Protocol):
    async def check(self, requirements: tuple[ConfinementFeature, ...]) -> ConfinementCheck: ...

    async def run_environment_create(
        self,
        distribution: PythonDistributionConfiguration,
        operation_id: RuntimeCorrelation,
        export_path: Path,
        helper_sha256: str,
        *,
        cancellation: CancellationService | None = None,
    ) -> ProbeEvidence: ...

    async def run_environment_verify(
        self,
        distribution: PythonDistributionConfiguration,
        operation_id: RuntimeCorrelation,
        environment_path: Path,
        helper_sha256: str,
        *,
        cancellation: CancellationService | None = None,
    ) -> ProbeEvidence: ...


class PythonEnvironmentRepository:
    def __init__(self, resources: PythonResourceRepository, storage: EnvironmentStorage) -> None:
        self.resources, self.storage = resources, storage

    def history(self, ref: RuntimeResourceRef) -> EmptyEnvironmentEvidence | None:
        with self.resources._database.transaction() as session:
            row = session.get(PythonEnvironmentRow, str(ref))
            if row is None:
                return None
            evidence = EmptyEnvironmentEvidence.model_validate_json(json.dumps(row.evidence_json))
            if (
                row.evidence_sha256 != digest_value(evidence)
                or str(evidence.operation_id) != row.operation_id
                or evidence.binding.resource_ref != ref
            ):
                raise EnvironmentFailure()
            return evidence

    def reconcile_retained(self) -> int:
        """Startup passive checks only; missing/drifted history never becomes usable."""
        with self.resources._database.transaction() as session:
            refs = tuple(row.resource_id for row in session.scalars(select(PythonEnvironmentRow)))
        rejected = 0
        from boberagent_contracts import ResourceRef

        for ref in refs:
            try:
                self.inspect_retained(ResourceRef(ref))
            except EnvironmentFailure:
                rejected += 1
        return rejected

    def inspect_retained(self, ref: RuntimeResourceRef) -> EmptyEnvironmentEvidence:
        """Passive integrity inspection, NOT fresh confined revalidation or usable lease."""
        try:
            evidence = self.history(ref)
            if evidence is None:
                raise EnvironmentFailure()
            actual = self.storage.verify_tree(
                self.storage.resource_directory(ref) / "venv", evidence.manifest, evidence.binding
            )
            if actual != evidence.environment:
                raise EnvironmentFailure()
            return evidence
        except (ValueError, OSError, EnvironmentFailure):
            self.resources.quarantine(ref, EnvironmentFailure().failure)
            raise EnvironmentFailure() from None

    def complete(self, claim: ResourceOperation, evidence: EmptyEnvironmentEvidence) -> None:
        evidence = EmptyEnvironmentEvidence.model_validate_json(evidence.model_dump_json())
        if (
            evidence.operation_id != claim.operation_id
            or evidence.binding.resource_ref != claim.resource_ref
            or evidence.generation != claim.generation
            or claim.operation is not PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT
        ):
            raise EnvironmentFailure()
        with self.resources._write() as session:
            detail, operation = self.resources._held(session, claim)
            self.resources._require_settled(session, operation)
            if (
                evidence.binding.request != self.resources._binding(detail)
                or detail.phase != "BUILDING"
            ):
                raise EnvironmentFailure()
            session.add(
                PythonEnvironmentRow(
                    resource_id=str(claim.resource_ref),
                    operation_id=str(claim.operation_id),
                    evidence_sha256=digest_value(evidence),
                    evidence_json=evidence.model_dump(mode="json"),
                )
            )
            session.add(
                WorkspaceRow(
                    workspace_id=detail.workspace_correlation,
                    owner_ref=str(claim.resource_ref),
                    purpose="python-empty-environment",
                    isolation="resource",
                    local_path=str(self.storage.resource_directory(claim.resource_ref)),
                    state="ACTIVE",
                    created_at=claim.started_at,
                )
            )
            session.flush()  # The VERIFYING guard requires evidence in this same transaction.
            detail.phase = "VERIFYING"
            self.resources._finish(detail, operation, OperationState.COMPLETED)
            self.resources._touch(session, detail)

    def begin(self, claim: ResourceOperation) -> None:
        with self.resources._write() as session:
            detail, _ = self.resources._held(session, claim)
            if detail.phase == "BUILDING":
                raise ConstructionInProgress()
            if detail.phase != "RESERVED":
                raise EnvironmentFailure()
            detail.phase = "BUILDING"
            self.resources._touch(session, detail)


def _operation_id(claim: ResourceOperation, suffix: str) -> RuntimeCorrelation:
    return DomainRef(
        "environment-" + suffix + "-" + hashlib.sha256(str(claim.operation_id).encode()).hexdigest()
    )


class PythonEnvironmentProvider:
    """Node composition only. The sole request is an authenticated Resource claim."""

    def __init__(
        self,
        *,
        distribution: PythonDistributionConfiguration,
        backend: EnvironmentBackend,
        backend_identity: PythonBackendIdentity,
        repository: PythonEnvironmentRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.distribution, self.backend, self.backend_identity = (
            distribution,
            backend,
            backend_identity,
        )
        self.repository, self._clock = repository, clock
        self.helper_sha256 = hashlib.sha256(
            Path(__file__).with_name("_environment_helper.py").read_bytes()
        ).hexdigest()

    async def create_empty_environment(
        self,
        claim: ResourceOperation,
        *,
        cancellation: CancellationService | None = None,
    ) -> EmptyEnvironmentEvidence:
        if claim.operation is not PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT:
            raise ValueError("exclusive construction claim required")
        resources, storage = self.repository.resources, self.repository.storage
        # A forged/mismatched caller must not quarantine somebody else's Resource.
        with resources._database.transaction() as session:
            resources._matching(session, claim)
        started, monotonic = self._clock(), time.monotonic()
        # Conservative controls plus exact measured environment writes on success.
        control_writes = 13 * (2 * 1024**2 + 8192) + 32 * 1024**2
        control_entries = 13 * 65 + 2 * 2050
        reservations = {
            BudgetCategory.TEMPORARY_BYTES: 144 * 1024**2 + 65536 + 8192,
            BudgetCategory.WRITE_BYTES: control_writes + 4 * WRITE_LIMIT + 2 * 65536 + 65536,
            BudgetCategory.FILE_COUNT: control_entries + 2 * FILE_LIMIT + 8,
            BudgetCategory.PATH_DEPTH: 4,
            BudgetCategory.PROCESSES: 11,
            BudgetCategory.MEMORY_BYTES: 136 * 1024**2,
            BudgetCategory.PROCESS_SECONDS: 38,
            BudgetCategory.TOTAL_SECONDS: 300,
            BudgetCategory.OUTPUT_BYTES: 15 * 4096,
        }
        try:
            retained = self.repository.history(claim.resource_ref)
            if retained is not None:
                with resources._database.transaction() as session:
                    old = resources._matching(session, claim)
                    if (
                        old.state != OperationState.COMPLETED.value
                        or retained.operation_id != claim.operation_id
                    ):
                        raise EnvironmentFailure()
                if resources.load(claim.resource_ref).phase.value != "VERIFYING":
                    raise EnvironmentFailure()
                if (
                    retained.helper_sha256 != self.helper_sha256
                    or _environment_distribution(self.distribution).identity()
                    != retained.binding.interpreter.distribution
                ):
                    raise EnvironmentFailure()
                return self.repository.inspect_retained(claim.resource_ref)
            if resources.remaining_operation_seconds(claim) < 300:
                raise EnvironmentFailure(PythonRuntimeReason.RUNTIME_LIMIT_UNAVAILABLE)
            provenance = PythonProvenanceRepository(resources).history(claim.resource_ref)
            if not provenance:
                raise EnvironmentFailure(PythonRuntimeReason.PYTHON_RUNTIME_UNAVAILABLE)
            prior = provenance[-1]
            manifest = _environment_distribution(self.distribution)
            if (
                prior.binding.interpreter.distribution != manifest.identity()
                or prior.binding.backend != self.backend_identity
                or prior.binding.request != resources.load(claim.resource_ref).request
            ):
                raise EnvironmentFailure()
            resources.reserve_budget(
                claim, tuple(BudgetAmount(category=k, amount=v) for k, v in reservations.items())
            )
            self.repository.begin(claim)
            directory = storage.reserve(claim.resource_ref)
            async with asyncio.timeout(295):
                if cancellation is not None:
                    await cancellation.checkpoint()
                check = await self.backend.check(tuple(ConfinementFeature))
                construction = await self.backend.run_environment_create(
                    self.distribution,
                    _operation_id(claim, "build"),
                    directory / "export",
                    self.helper_sha256,
                    cancellation=cancellation,
                )
                # Enforcement validates fresh thirteen controls and backend/boot pins.
                enforcement(check, construction)
                if (
                    not construction.passed
                    or not construction.group_empty
                    or construction.exit_code != 0
                    or construction.stderr_hex
                ):
                    raise EnvironmentFailure(PythonRuntimeReason.VENV_CREATION_FAILED)
                summary = ConstructionSummary.model_validate_json(
                    bytes.fromhex(construction.stdout_hex)
                )
                environment_manifest = storage.publish(claim.resource_ref, prior.binding)
                if (
                    summary.written_bytes != environment_manifest.written_bytes
                    or summary.created_entries != environment_manifest.created_entries
                    or summary.export_bytes != (directory / "export").stat().st_size
                ):
                    raise EnvironmentFailure()
                environment = storage.verify_tree(
                    directory / "venv", environment_manifest, prior.binding
                )
                verification = await self.backend.run_environment_verify(
                    self.distribution,
                    _operation_id(claim, "verify"),
                    directory / "venv",
                    self.helper_sha256,
                    cancellation=cancellation,
                )
                enforcement(check, verification)
                identity = EnvironmentIdentity.model_validate_json(
                    bytes.fromhex(verification.stdout_hex)
                )
                if (
                    identity.version != prior.binding.interpreter.summary.python_version
                    or identity.paths
                    != (
                        "/runtime/lib/python312.zip",
                        "/runtime/lib/python3.12",
                        "/runtime/lib/python3.12/lib-dynload",
                        "/work/venv/lib/python3.12/site-packages",
                    )
                ):
                    raise EnvironmentFailure()
                if cancellation is not None:
                    await cancellation.checkpoint()
                if (
                    inventory(self.distribution) != manifest
                    or storage.verify_tree(directory / "venv", environment_manifest, prior.binding)
                    != environment
                ):
                    raise EnvironmentFailure()
                elapsed = ceil((time.monotonic() - monotonic) * 1000)
                actual_writes = environment_manifest.written_bytes * 2 + summary.export_bytes * 2
                actual_files = environment_manifest.created_entries * 2
                evidence = EmptyEnvironmentEvidence(
                    binding=prior.binding,
                    operation_id=claim.operation_id,
                    generation=claim.generation,
                    helper_sha256=self.helper_sha256,
                    provenance=prior,
                    manifest=environment_manifest,
                    environment=environment,
                    construction=construction,
                    verification=verification,
                    committed_write_bytes=actual_writes,
                    committed_file_count=actual_files,
                    started_at=started,
                    completed_at=self._clock(),
                )
                if len(
                    evidence.model_dump_json().encode()
                ) > 65536 or python_runtime_binding_digest(
                    prior.binding
                ) != python_runtime_binding_digest(evidence.binding):
                    raise EnvironmentFailure()
                settled = dict(reservations)
                settled[BudgetCategory.WRITE_BYTES] = control_writes + actual_writes + 65536
                settled[BudgetCategory.FILE_COUNT] = control_entries + actual_files + 8
                settled[BudgetCategory.TOTAL_SECONDS] = ceil(elapsed / 1000)
                settled[BudgetCategory.OUTPUT_BYTES] = sum(
                    (len(p.stdout_hex) + len(p.stderr_hex)) // 2
                    for p in (*check.probes, construction, verification)
                )
                resources.settle_budget(
                    claim, tuple(BudgetAmount(category=k, amount=v) for k, v in settled.items())
                )
                self.repository.complete(claim, evidence)
                return evidence
        except BaseException as error:
            if isinstance(error, ConstructionInProgress):
                raise  # A duplicate caller cannot poison the active constructor.
            failure = getattr(error, "failure", None)
            if not isinstance(failure, PythonRuntimeFailure):
                failure = PythonRuntimeFailure(
                    reason_code=(
                        error.code
                        if isinstance(error, ResourceOwnershipError)
                        else PreparationReasonCode.PREPARATION_CANCELLED
                        if isinstance(error, asyncio.CancelledError)
                        else PreparationReasonCode.PREPARATION_INTERRUPTED
                    )
                )
            resources.quarantine(claim.resource_ref, failure)
            if isinstance(
                error,
                (
                    EnvironmentFailure,
                    ResourceOwnershipError,
                    RuntimeConfinementUnavailable,
                    asyncio.CancelledError,
                ),
            ):
                raise
            raise EnvironmentFailure(PythonRuntimeReason.RUNTIME_QUARANTINED) from None
