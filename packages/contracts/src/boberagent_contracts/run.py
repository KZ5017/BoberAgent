"""CapabilityRun lifecycle snapshot."""

from pydantic import AwareDatetime

from ._base import ContractModel
from .capability import CapabilityId, OperationName
from .enums import CapabilityRunStatus
from .refs import CapabilityRunRef, MissionRef, WorkflowRunRef


class CapabilityRun(ContractModel):
    """One concrete Capability operation execution."""

    run_id: CapabilityRunRef
    capability_id: CapabilityId
    operation: OperationName
    mission_ref: MissionRef
    status: CapabilityRunStatus
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    parent_run_ref: CapabilityRunRef | None = None
    workflow_run_ref: WorkflowRunRef | None = None

    @property
    def is_terminal(self) -> bool:
        """Expose terminal semantics without implementing a runtime state machine."""

        return self.status.is_terminal
