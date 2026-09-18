"""Core-owned Workflow state and definition failures."""


class WorkflowError(RuntimeError):
    """Base error for deterministic Workflow orchestration."""


class WorkflowNotFound(WorkflowError):
    pass


class WorkflowDefinitionConflict(WorkflowError):
    pass


class WorkflowStateError(WorkflowError):
    pass
