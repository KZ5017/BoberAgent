"""Node-owned bookkeeping, not interpreter evidence or execution authority."""

from enum import StrEnum

from boberagent_contracts import (
    PythonProviderOperation,
    PythonProviderPhase,
    PythonResourceState,
    PythonRuntimeFailure,
    PythonRuntimeRequestBinding,
    PythonRuntimeValidity,
    Sha256Digest,
)
from boberagent_contracts.python_runtime import RuntimeCorrelation, RuntimeResourceRef
from pydantic import AwareDatetime, Field, StrictInt

from ..persistence.models import RuntimeModel


class OperationState(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class CleanupState(StrEnum):
    NONE = "NONE"
    PENDING = "PENDING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class BudgetCategory(StrEnum):
    IMPORTED_BYTES = "max_imported_artifact_bytes"
    MATERIALIZED_BYTES = "max_materialized_bytes"
    FILE_COUNT = "max_file_count"
    PATH_DEPTH = "max_path_depth"
    TEMPORARY_BYTES = "max_temporary_bytes"
    WRITE_BYTES = "max_preparation_write_bytes"
    PROCESSES = "max_processes"
    PROCESS_SECONDS = "max_process_runtime_seconds"
    TOTAL_SECONDS = "max_total_runtime_seconds"
    OUTPUT_BYTES = "max_captured_output_bytes"
    MEMORY_BYTES = "max_memory_bytes"


PEAK_CATEGORIES = frozenset(
    {
        BudgetCategory.PATH_DEPTH,
        BudgetCategory.TEMPORARY_BYTES,
        BudgetCategory.PROCESSES,
        BudgetCategory.PROCESS_SECONDS,
        BudgetCategory.MEMORY_BYTES,
    }
)


class BudgetAmount(RuntimeModel):
    category: BudgetCategory
    amount: StrictInt = Field(ge=0)


class BudgetBalance(RuntimeModel):
    category: BudgetCategory
    limit: int
    committed: int
    held: int
    available: int


class PythonResourceReservation(RuntimeModel):
    resource_ref: RuntimeResourceRef
    request: PythonRuntimeRequestBinding
    request_sha256: Sha256Digest
    workspace_correlation: RuntimeCorrelation
    state: PythonResourceState
    phase: PythonProviderPhase
    validity: PythonRuntimeValidity
    generation: int
    active_operation_id: RuntimeCorrelation | None
    cleanup: CleanupState
    failure: PythonRuntimeFailure | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ResourceOperation(RuntimeModel):
    resource_ref: RuntimeResourceRef
    operation_id: RuntimeCorrelation
    operation: PythonProviderOperation
    owner_token: RuntimeCorrelation
    boot_generation: RuntimeCorrelation
    generation: int
    state: OperationState
    started_at: AwareDatetime
    expires_at: AwareDatetime
    finished_at: AwareDatetime | None
    failure: PythonRuntimeFailure | None
