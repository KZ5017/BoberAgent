"""Connect closed probes to the E5-B ledger without changing its ownership rules."""

from boberagent_contracts import PreparationReasonCode, PythonRuntimeFailure

from .resource_models import BudgetAmount, BudgetCategory, ResourceOperation
from .resources import PythonResourceRepository
from .runtime_confinement import RuntimeConfinementBackend
from .runtime_confinement_models import ClosedProbe, ProbeEvidence, ProbeLimits


async def run_budgeted_probe(
    backend: RuntimeConfinementBackend,
    repository: PythonResourceRepository,
    claim: ResourceOperation,
    probe: ClosedProbe,
    limits: ProbeLimits,
) -> ProbeEvidence:
    """One existing exclusive claim, one closed probe, immutable reservation.

    Mechanism validation is a prerequisite of the later inspect action, not an
    invocation of Python. Caller has already authenticated that E5-B claim.
    Reserve conservative writes/control overhead; never relabel bounds as exact
    measurements. Interrupted work consumes its full reservation by E5-B policy.
    """
    if repository.remaining_operation_seconds(claim) < limits.seconds + 8:
        raise ValueError("insufficient admitted time for trusted operation and teardown")
    values = {
        BudgetCategory.TEMPORARY_BYTES: limits.scratch_bytes + 8192 + 4096,
        BudgetCategory.WRITE_BYTES: 2 * 1024 * 1024 + 4096 + limits.output_bytes,
        BudgetCategory.FILE_COUNT: 65,
        BudgetCategory.PROCESSES: limits.processes + 3,  # guardian/supervisor/test requester
        BudgetCategory.MEMORY_BYTES: limits.memory_bytes + 8 * 1024 * 1024,
        BudgetCategory.PROCESS_SECONDS: limits.seconds + 8,
        BudgetCategory.TOTAL_SECONDS: limits.seconds + 8,
        BudgetCategory.OUTPUT_BYTES: limits.output_bytes,
    }
    amounts = tuple(BudgetAmount(category=key, amount=value) for key, value in values.items())
    repository.reserve_budget(claim, amounts)
    try:
        result = await backend.run_closed(probe, claim.operation_id, limits)
        if not result.passed:
            raise ValueError("trusted confinement probe failed")
        # Only time/output have reliable exact deltas here. Other amounts remain
        # explicitly conservative reservations, not fabricated kernel measurements.
        values[BudgetCategory.TOTAL_SECONDS] = (result.duration_milliseconds + 999) // 1000
        values[BudgetCategory.PROCESS_SECONDS] = values[BudgetCategory.TOTAL_SECONDS]
        values[BudgetCategory.OUTPUT_BYTES] = (len(result.stdout_hex) + len(result.stderr_hex)) // 2
        repository.settle_budget(
            claim, tuple(BudgetAmount(category=key, amount=value) for key, value in values.items())
        )
        repository.release_claim(claim)
        return result
    except BaseException:
        repository.quarantine(
            claim.resource_ref,
            PythonRuntimeFailure(reason_code=PreparationReasonCode.PREPARATION_INTERRUPTED),
        )
        raise
