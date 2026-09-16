"""Capability invocation envelope."""

from pydantic import Field

from ._base import ContractModel, JsonObject
from .capability import CapabilityId, OperationName
from .refs import CapabilityRunRef, MissionRef, WorkflowRunRef


class CapabilityInvocation(ContractModel):
    """Validated request to execute one Capability operation."""

    run_id: CapabilityRunRef
    capability_id: CapabilityId
    operation: OperationName
    mission_ref: MissionRef
    inputs: JsonObject = Field(default_factory=dict)
    parent_run_ref: CapabilityRunRef | None = None
    workflow_run_ref: WorkflowRunRef | None = None
