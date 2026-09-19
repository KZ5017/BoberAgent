"""Local-only Capability execution coordinator."""

from __future__ import annotations

from datetime import datetime

from boberagent_contracts import (
    CapabilityInvocation,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunRef,
    CapabilityRunStatus,
    Diagnostic,
    DiagnosticSeverity,
)
from boberagent_sdk import (
    CapabilityError,
    DependencyError,
    ExecutionCancelled,
    ExecutionTimeout,
    InputError,
    InvocationContext,
    PolicyDenied,
    ResourceUnavailable,
    ResultValidationError,
    ScopeViolation,
    SessionUnavailable,
    ToolExecutionError,
    UtcClock,
)
from pydantic import ValidationError

from boberagent_execution_node.persistence import RunRecord, RuntimeStore
from boberagent_execution_node.results import ResultOutbox
from boberagent_execution_node.services import (
    ContextBundle,
    ExecutionContextFactory,
    LocalInvocationEnvironment,
)
from boberagent_execution_node.tools import DependencyResolver

from .registry import CapabilityLoadError, LocalCapabilityRegistry


class CapabilityRuntime:
    def __init__(
        self,
        *,
        registry: LocalCapabilityRegistry,
        dependencies: DependencyResolver,
        contexts: ExecutionContextFactory,
        store: RuntimeStore,
        results: ResultOutbox,
    ) -> None:
        self._registry = registry
        self._dependencies = dependencies
        self._contexts = contexts
        self._store = store
        self._results = results
        self._clock = UtcClock()
        self._active: dict[str, ContextBundle] = {}

    async def execute(
        self,
        invocation: CapabilityInvocation,
        environment: LocalInvocationEnvironment,
        *,
        invocation_fingerprint: str | None = None,
    ) -> CapabilityResult:
        existing = self._store.get_run(invocation.run_id)
        if existing is not None:
            stored_result = self._results.get(invocation.run_id)
            if stored_result is not None:
                return stored_result
            raise CapabilityError(
                f"CapabilityRun already exists locally without a replayable result: "
                f"{invocation.run_id} ({existing.status})"
            )

        now = self._clock.now()
        self._store.add_run(
            RunRecord(
                run_ref=invocation.run_id,
                mission_ref=invocation.mission_ref,
                capability_id=invocation.capability_id,
                operation=invocation.operation,
                status=CapabilityRunStatus.CREATED,
                created_at=now,
                parent_run_ref=invocation.parent_run_ref,
                workflow_run_ref=invocation.workflow_run_ref,
                invocation_fingerprint=invocation_fingerprint,
            )
        )
        invocation_context = InvocationContext(
            run_id=invocation.run_id,
            capability_id=invocation.capability_id,
            operation=invocation.operation,
            mission_ref=invocation.mission_ref,
            parent_run_ref=invocation.parent_run_ref,
            workflow_run_ref=invocation.workflow_run_ref,
        )
        bundle = self._contexts.create(invocation_context, environment)
        self._active[str(invocation.run_id)] = bundle
        try:
            result = await self._execute_started(invocation, bundle)
        except Exception as error:
            result, error_code = _failure_result(invocation.run_id, error, self._clock.now())
            finished_at = self._clock.now()
            self._results.persist_terminal(result, finished_at=finished_at, error_code=error_code)
            bundle.events.runtime_event(
                "capability.run.failed",
                {
                    "capability_id": invocation.capability_id,
                    "status": result.execution_status.value,
                    "error_code": error_code,
                },
            )
            return result
        finally:
            self._active.pop(str(invocation.run_id), None)

        self._results.persist_terminal(result, finished_at=self._clock.now())
        terminal_event_type = (
            "capability.run.completed"
            if result.execution_status is CapabilityRunStatus.COMPLETED
            else "capability.run.failed"
        )
        bundle.events.runtime_event(
            terminal_event_type,
            {
                "capability_id": invocation.capability_id,
                "status": result.execution_status.value,
            },
        )
        return result

    async def _execute_started(
        self,
        invocation: CapabilityInvocation,
        bundle: ContextBundle,
    ) -> CapabilityResult:
        provider = self._registry.get(invocation.capability_id)
        operations = {operation.name for operation in provider.definition.operations}
        if invocation.operation not in operations:
            raise InputError(f"operation is not declared: {invocation.operation}")
        self._dependencies.require(provider.definition)
        input_model = provider.load_input_model(invocation.operation)
        try:
            inputs = input_model.model_validate(invocation.inputs)
        except ValidationError as error:
            raise InputError("invocation inputs failed provider validation") from error
        implementation = provider.load_implementation()

        started_at = self._clock.now()
        self._store.update_run(
            invocation.run_id,
            CapabilityRunStatus.RUNNING,
            started_at=started_at,
        )
        bundle.events.runtime_event(
            "capability.run.started", {"capability_id": invocation.capability_id}
        )
        returned = await implementation.execute(invocation.operation, bundle.context, inputs)
        if not isinstance(returned, CapabilityResult):
            raise ResultValidationError("capability returned a non-CapabilityResult value")
        try:
            result = CapabilityResult.model_validate(returned.model_dump())
        except ValidationError as error:
            raise ResultValidationError("CapabilityResult validation failed") from error
        if result.run_ref != invocation.run_id:
            raise ResultValidationError("CapabilityResult run_ref does not match invocation")
        return result

    def cancel(self, run_ref: str) -> bool:
        bundle = self._active.get(run_ref)
        if bundle is None:
            return False
        bundle.cancellation.request()
        return True


def interrupted_result(record: RunRecord, occurred_at: datetime) -> CapabilityResult:
    return CapabilityResult(
        run_ref=record.run_ref,
        execution_status=CapabilityRunStatus.FAILED,
        outcome=CapabilityOutcome(
            category=CapabilityOutcomeCategory.UNKNOWN,
            code="INTERRUPTED_EXECUTION_STATE_UNKNOWN",
            summary="Node restart left execution outcome unknown.",
        ),
        diagnostics=(
            Diagnostic(
                code="INTERRUPTED_EXECUTION_STATE_UNKNOWN",
                severity=DiagnosticSeverity.ERROR,
                message="The node could not prove completion of an interrupted execution.",
                occurred_at=occurred_at,
                run_ref=record.run_ref,
            ),
        ),
    )


def _failure_result(
    run_ref: CapabilityRunRef, error: Exception, occurred_at: datetime
) -> tuple[CapabilityResult, str]:
    if isinstance(error, ExecutionCancelled):
        status = CapabilityRunStatus.CANCELLED
        code = "EXECUTION_CANCELLED"
        message = "Capability execution was cancelled."
    elif isinstance(error, ExecutionTimeout):
        status = CapabilityRunStatus.TIMED_OUT
        code = "EXECUTION_TIMED_OUT"
        message = "Capability execution timed out."
    elif isinstance(error, DependencyError):
        status = CapabilityRunStatus.FAILED
        code = "DEPENDENCY_UNAVAILABLE"
        message = "A required local dependency was unavailable."
    elif isinstance(error, ResourceUnavailable):
        status = CapabilityRunStatus.FAILED
        code = "RESOURCE_UNAVAILABLE"
        message = "A required managed Resource was unavailable."
    elif isinstance(error, SessionUnavailable):
        status = CapabilityRunStatus.FAILED
        code = "SESSION_UNAVAILABLE"
        message = "A required stateful Session was unavailable."
    elif isinstance(error, ScopeViolation):
        status = CapabilityRunStatus.FAILED
        code = "SCOPE_VIOLATION"
        message = "Local scope enforcement denied the operation."
    elif isinstance(error, PolicyDenied):
        status = CapabilityRunStatus.FAILED
        code = "POLICY_DENIED"
        message = "Local policy denied the operation."
    elif isinstance(error, InputError):
        status = CapabilityRunStatus.FAILED
        code = "INPUT_INVALID"
        message = "Capability input validation failed."
    elif isinstance(error, ToolExecutionError):
        status = CapabilityRunStatus.FAILED
        code = "TOOL_EXECUTION_FAILED"
        message = "Managed tool execution failed."
    elif isinstance(error, (CapabilityLoadError, ResultValidationError)):
        status = CapabilityRunStatus.FAILED
        code = "IMPLEMENTATION_INVALID"
        message = "The local capability provider produced invalid runtime behavior."
    else:
        status = CapabilityRunStatus.FAILED
        code = "UNHANDLED_IMPLEMENTATION_ERROR"
        message = "Capability execution failed with an unexpected implementation error."
    result = CapabilityResult(
        run_ref=run_ref,
        execution_status=status,
        outcome=CapabilityOutcome(
            category=CapabilityOutcomeCategory.UNKNOWN,
            code=code,
            summary=message,
        ),
        diagnostics=(
            Diagnostic(
                code=code,
                severity=DiagnosticSeverity.ERROR,
                message=message,
                occurred_at=occurred_at,
                run_ref=run_ref,
                details={"exception_type": type(error).__name__},
            ),
        ),
    )
    return result, code
