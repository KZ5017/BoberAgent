"""Fixed CPython identity validation and Resource-owned immutable provenance.

This is not an SDK capability, environment builder, readiness or execution grant.
Resource ownership/authority and accounting are still enforced by E5-B.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from math import ceil
from typing import Literal, Protocol

from boberagent_contracts import (
    ConfinementFeature,
    InterpreterEvidence,
    PreparationUsage,
    PythonBackendIdentity,
    PythonInterpreterIdentity,
    PythonProviderOperation,
    PythonRuntimeBinding,
    PythonRuntimeEnforcement,
    PythonRuntimeEvidence,
    PythonRuntimeNonActions,
    PythonRuntimeOutputEvidence,
    PythonRuntimeReason,
    PythonWritableMount,
    python_runtime_binding_digest,
    python_runtime_evidence_digest,
)
from boberagent_contracts.python_runtime import RuntimeCorrelation, RuntimeResourceRef
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, ValidationError
from sqlalchemy import select

from ..persistence.orm import PythonRuntimeEvidenceRow
from .python_distribution import (
    DistributionManifest,
    ProvenanceFailure,
    PythonDistributionConfiguration,
    digest_value,
    inventory,
)
from .resource_models import BudgetAmount, BudgetCategory, OperationState, ResourceOperation
from .resources import PythonResourceRepository, ResourceOwnershipError
from .runtime_confinement import RuntimeConfinementUnavailable
from .runtime_confinement_models import (
    ConfinementCheck,
    ProbeEvidence,
    TrustedPythonOperation,
)


class IdentityResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    implementation: Literal["cpython"]
    version: str
    platform: Literal["linux"]
    architecture: Literal["x86_64"]
    cache_tag: Literal["cpython-312"]
    soabi: Literal["cpython-312-x86_64-linux-gnu"]
    prefix: Literal["/runtime"]
    base_prefix: Literal["/runtime"]
    executable: Literal["/runtime/bin/python3.12"]
    paths: list[str]
    isolated: StrictInt
    no_site: StrictInt
    no_bytecode: StrictBool


def validate_identity(
    manifest: DistributionManifest, probe: ProbeEvidence
) -> PythonInterpreterIdentity:
    try:
        if (
            probe.probe is not TrustedPythonOperation.IDENTITY
            or not probe.passed
            or not probe.attached_before_exec
            or not probe.group_empty
            or probe.exit_code != 0
            or probe.pids_events
            or probe.oom_events
            or probe.stderr_hex
        ):
            raise ValueError("incomplete identity proof")
        identity = IdentityResult.model_validate_json(bytes.fromhex(probe.stdout_hex))
        if (
            identity.paths
            != [
                "/runtime/lib/python312.zip",
                "/runtime/lib/python3.12",
                "/runtime/lib/python3.12/lib-dynload",
            ]
            or identity.isolated != 1
            or identity.no_site != 1
            or not identity.no_bytecode
        ):
            raise ValueError("untrusted interpreter search path/flags")
        return PythonInterpreterIdentity(
            summary=InterpreterEvidence(
                registry_tool="python-runtime-3.12",
                executable_sha256=manifest.interpreter_sha256,
                python_version=identity.version,
                platform="linux",
                abi="cpython-312",
                runtime_fingerprint=manifest.digest,
            ),
            implementation="CPython",
            build_identity=digest_value(identity),
            architecture="x86_64",
            soabi=identity.soabi,
            cache_tag=identity.cache_tag,
            base_layout="m20-e5-uv-python@1",
            stdlib_layout="m20-e5-uv-stdlib@1",
            closure_sha256=manifest.digest,
            distribution=manifest.identity(),
        )
    except (ValidationError, ValueError):
        raise ProvenanceFailure(
            PythonRuntimeReason.PYTHON_RUNTIME_MISMATCH, "identity_result"
        ) from None


class IdentityBackend(Protocol):
    async def check(self, requirements: tuple[ConfinementFeature, ...]) -> ConfinementCheck: ...

    async def run_identity(
        self, distribution: PythonDistributionConfiguration, operation_id: RuntimeCorrelation
    ) -> ProbeEvidence: ...


class PythonProvenanceRepository:
    """Narrow extension of the existing Resource ledger, not a second Resource store."""

    def __init__(self, resources: PythonResourceRepository) -> None:
        self.resources = resources

    def history(self, ref: RuntimeResourceRef) -> tuple[PythonRuntimeEvidence, ...]:
        with self.resources._database.transaction() as session:
            rows = session.scalars(
                select(PythonRuntimeEvidenceRow)
                .where(PythonRuntimeEvidenceRow.resource_id == str(ref))
                .order_by(PythonRuntimeEvidenceRow.operation_id)
            )
            result = []
            for row in rows:
                evidence = PythonRuntimeEvidence.model_validate_json(json.dumps(row.evidence_json))
                manifest = DistributionManifest.model_validate(row.manifest_json)
                if (
                    python_runtime_evidence_digest(evidence) != row.evidence_sha256
                    or python_runtime_binding_digest(evidence.binding) != row.binding_sha256
                    or manifest.identity() != evidence.binding.interpreter.distribution
                ):
                    raise ProvenanceFailure(
                        PythonRuntimeReason.RUNTIME_INTEGRITY_FAILURE, "retained_evidence"
                    )
                result.append(evidence)
            return tuple(result)

    def complete(
        self,
        claim: ResourceOperation,
        evidence: PythonRuntimeEvidence,
        manifest: DistributionManifest,
    ) -> None:
        evidence = PythonRuntimeEvidence.model_validate_json(evidence.model_dump_json())
        manifest = DistributionManifest.model_validate_json(manifest.model_dump_json())
        if (
            evidence.verification != "PROVENANCE_VERIFIED"
            or claim.operation is not PythonProviderOperation.INSPECT_INTERPRETER
            or evidence.binding.resource_ref != claim.resource_ref
            or evidence.budget_ledger_correlation != claim.operation_id
            or evidence.binding.interpreter.distribution != manifest.identity()
        ):
            raise ProvenanceFailure(
                PythonRuntimeReason.RUNTIME_IDENTITY_CONFLICT, "evidence_binding"
            )
        with self.resources._write() as session:
            previous = session.get(PythonRuntimeEvidenceRow, str(claim.operation_id))
            if previous is not None:
                self.resources._matching(session, claim)
                if previous.evidence_sha256 != python_runtime_evidence_digest(evidence):
                    raise ProvenanceFailure(
                        PythonRuntimeReason.RUNTIME_IDENTITY_CONFLICT, "evidence_replay"
                    )
                return
            detail, operation = self.resources._held(session, claim)
            self.resources._require_settled(session, operation)
            if (
                evidence.binding.request != self.resources._binding(detail)
                or str(evidence.workspace_correlation) != detail.workspace_correlation
            ):
                raise ProvenanceFailure(
                    PythonRuntimeReason.RUNTIME_IDENTITY_CONFLICT, "resource_binding"
                )
            binding_digest = python_runtime_binding_digest(evidence.binding)
            first = session.scalar(
                select(PythonRuntimeEvidenceRow).where(
                    PythonRuntimeEvidenceRow.resource_id == str(claim.resource_ref)
                )
            )
            if first is not None and first.binding_sha256 != binding_digest:
                raise ProvenanceFailure(
                    PythonRuntimeReason.RUNTIME_IDENTITY_CONFLICT, "sealed_binding"
                )
            session.add(
                PythonRuntimeEvidenceRow(
                    operation_id=str(claim.operation_id),
                    resource_id=str(claim.resource_ref),
                    binding_sha256=binding_digest,
                    evidence_sha256=python_runtime_evidence_digest(evidence),
                    evidence_json=evidence.model_dump(mode="json"),
                    manifest_json=manifest.model_dump(mode="json"),
                )
            )
            self.resources._finish(detail, operation, OperationState.COMPLETED)
            self.resources._touch(session, detail)


def enforcement(check: ConfinementCheck, probe: ProbeEvidence) -> PythonRuntimeEnforcement:
    from .runtime_confinement_models import ClosedProbe

    if (
        set(check.features) != set(ConfinementFeature)
        or len(check.probes) != len(ClosedProbe)
        or {p.probe for p in check.probes} != set(ClosedProbe)
        or any(
            not p.passed or not p.group_empty or not p.attached_before_exec for p in check.probes
        )
        or any(
            p.helper_sha256 != probe.helper_sha256
            or p.bubblewrap_sha256 != probe.bubblewrap_sha256
            or p.boot_generation != probe.boot_generation
            for p in check.probes
        )
    ):
        raise ProvenanceFailure(
            PythonRuntimeReason.DESCENDANT_CONTAINMENT_UNAVAILABLE, "fresh_controls"
        )
    limits = probe.limits
    paths: tuple[Literal["/work/venv", "/work/tmp", "/work/home"], ...] = (
        "/work/venv",
        "/work/tmp",
        "/work/home",
    )
    return PythonRuntimeEnforcement(
        kernel_version=probe.kernel,
        boot_generation=probe.boot_generation,
        verified_features=tuple(ConfinementFeature),
        passed_probes=tuple(ConfinementFeature),
        process_mechanism="CGROUP_V2_PIDS_MAX",
        memory_mechanism="CGROUP_V2_MEMORY_MAX_ZERO_SWAP_GROUP_OOM",
        descendant_mechanism="CGROUP_KILL_SUPERVISED_PID_NAMESPACE",
        storage_mechanism="CAPPED_TMPFS_BOUNDED_TRUSTED_PUBLISHER",
        runtime_mechanism="SUPERVISED_MONOTONIC_DEADLINES",
        output_mechanism="COMBINED_CAPPED_PIPE_DRAIN",
        network_mechanism="EMPTY_NETWORK_NAMESPACE_NO_SOCKET_FDS",
        filesystem_policy="MINIMAL_READONLY_VIEW_NO_WRITABLE_HOST_BIND",
        source_visibility="ABSENT_DURING_PYTHON_OPERATIONS",
        effective_process_limit=limits.processes,
        effective_memory_bytes=limits.memory_bytes,
        effective_swap_bytes=0,
        effective_process_seconds=limits.seconds,
        effective_total_seconds=limits.seconds,
        effective_output_bytes=limits.output_bytes,
        effective_write_bytes=limits.scratch_bytes + 8192,
        writable_mounts=tuple(
            PythonWritableMount(
                namespace_path=path,
                mechanism="SIZED_INODE_BOUNDED_TMPFS",
                max_bytes=limits.scratch_bytes if path == "/work/venv" else 4096,
                max_inodes=limits.scratch_inodes if path == "/work/venv" else 8,
            )
            for path in paths
        ),
        pids_limit_events=probe.pids_events,
        oom_events=probe.oom_events,
        memory_peak_bytes=probe.memory_peak,
        processes_peak=limits.processes,
        descendants_empty=True,
    )


async def inspect_owned_interpreter(
    configuration: PythonDistributionConfiguration,
    backend: IdentityBackend,
    backend_identity: PythonBackendIdentity,
    repository: PythonProvenanceRepository,
    claim: ResourceOperation,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PythonRuntimeEvidence:
    """One authenticated E5-B inspect claim. Failure quarantines, never infers READY."""
    resources = repository.resources
    if claim.operation is not PythonProviderOperation.INSPECT_INTERPRETER:
        raise ValueError("interpreter inspection ownership required")
    # Maxima include all fresh thirteen probes, static hashing and safe teardown.
    reservations = {
        BudgetCategory.TEMPORARY_BYTES: 1024**2 + 12288,
        BudgetCategory.WRITE_BYTES: 14 * (2 * 1024**2 + 8192),
        BudgetCategory.FILE_COUNT: 14 * 65,
        BudgetCategory.PROCESSES: 11,
        BudgetCategory.MEMORY_BYTES: 72 * 1024**2,
        BudgetCategory.PROCESS_SECONDS: 11,
        BudgetCategory.TOTAL_SECONDS: 214,
        BudgetCategory.OUTPUT_BYTES: 14 * 4096,
    }
    started, monotonic = clock(), time.monotonic()
    try:
        if resources.remaining_operation_seconds(claim) < 214:
            raise ProvenanceFailure(PythonRuntimeReason.RUNTIME_LIMIT_UNAVAILABLE, "authority_time")
        resources.reserve_budget(
            claim, tuple(BudgetAmount(category=k, amount=v) for k, v in reservations.items())
        )
        async with asyncio.timeout(210):
            # Static proof must precede any candidate execution or namespace bind.
            manifest = inventory(configuration)
            check = await backend.check(tuple(ConfinementFeature))
            probe = await backend.run_identity(configuration, claim.operation_id)
            identity = validate_identity(manifest, probe)
            if inventory(configuration) != manifest:
                raise ProvenanceFailure(
                    PythonRuntimeReason.RUNTIME_INTEGRITY_FAILURE, "post_identity"
                )
            if (
                probe.helper_sha256 != backend_identity.helper_sha256
                or probe.bubblewrap_sha256 != backend_identity.binary_sha256
            ):
                raise ProvenanceFailure(
                    PythonRuntimeReason.RUNTIME_IDENTITY_CONFLICT, "backend_binding"
                )
            proof = enforcement(check, probe)
            elapsed = ceil((time.monotonic() - monotonic) * 1000)
            settled = dict(reservations)
            settled[BudgetCategory.TOTAL_SECONDS] = ceil(elapsed / 1000)
            settled[BudgetCategory.OUTPUT_BYTES] = sum(
                (len(p.stdout_hex) + len(p.stderr_hex)) // 2 for p in (*check.probes, probe)
            )
            resources.settle_budget(
                claim, tuple(BudgetAmount(category=k, amount=v) for k, v in settled.items())
            )
            reservation = resources.load(claim.resource_ref)
            balances = {b.category: b.committed for b in resources.budget(claim.resource_ref)}
            fields = {
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
            aggregate = PreparationUsage(**{field: balances[key] for key, field in fields.items()})
            usage = PreparationUsage(
                **{field: settled.get(key, 0) for key, field in fields.items()}
            )
            evidence = PythonRuntimeEvidence(
                schema_version="PythonRuntimeEvidence-v1",
                binding=PythonRuntimeBinding(
                    schema_version="python-runtime-binding-v1",
                    resource_ref=claim.resource_ref,
                    request=reservation.request,
                    interpreter=identity,
                    backend=backend_identity,
                ),
                workspace_correlation=reservation.workspace_correlation,
                operation=claim.operation,
                environment=None,
                non_actions=PythonRuntimeNonActions(
                    source_imported=False,
                    source_compiled=False,
                    entrypoint_executed=False,
                    package_installed=False,
                    activation_script_sourced=False,
                    preparation_network="NONE",
                ),
                enforcement=proof,
                aggregate_usage=aggregate,
                e5_usage=usage,
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
                verification="PROVENANCE_VERIFIED",
                failure=None,
                evidence_artifact_refs=(),
            )
            repository.complete(claim, evidence, manifest)
            return evidence
    except BaseException as error:
        if isinstance(error, (ProvenanceFailure, RuntimeConfinementUnavailable)):
            failure = error.failure
        else:
            from boberagent_contracts import PreparationReasonCode, PythonRuntimeFailure

            if isinstance(error, TimeoutError):
                failure = ProvenanceFailure(
                    PythonRuntimeReason.RUNTIME_LIMIT_UNAVAILABLE, "operation_deadline"
                ).failure
            else:
                failure = PythonRuntimeFailure(
                    reason_code=error.code
                    if isinstance(error, ResourceOwnershipError)
                    else PreparationReasonCode.PREPARATION_INTERRUPTED
                )
        resources.quarantine(claim.resource_ref, failure)
        if isinstance(
            error,
            (
                ProvenanceFailure,
                RuntimeConfinementUnavailable,
                ResourceOwnershipError,
                asyncio.CancelledError,
            ),
        ):
            raise
        if isinstance(error, TimeoutError):
            raise ProvenanceFailure(
                PythonRuntimeReason.RUNTIME_LIMIT_UNAVAILABLE, "operation_deadline"
            ) from None
        raise ProvenanceFailure(
            PythonRuntimeReason.RUNTIME_QUARANTINED, "operation_interrupted"
        ) from None
