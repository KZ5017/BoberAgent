"""Capability entry point and read-only ExecutionContext tests."""

import asyncio
import inspect

import pytest
from boberagent_contracts import (
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunStatus,
)
from boberagent_sdk import Capability, ExecutionContext
from boberagent_sdk.testing import FakeExecutionContext
from pydantic import BaseModel, ValidationError


class EmptyInput(BaseModel):
    pass


class MinimalCapability(Capability):
    capability_id = "test.minimal"

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        del operation, inputs
        return CapabilityResult(
            run_ref=ctx.invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(category=CapabilityOutcomeCategory.SUCCESS),
        )


def test_capability_async_interface_and_identifier() -> None:
    context = FakeExecutionContext()
    try:
        capability = MinimalCapability()
        result = asyncio.run(capability.execute("execute", context, EmptyInput()))
        assert inspect.iscoroutinefunction(capability.execute)
        assert capability.capability_id == "test.minimal"
        assert result.run_ref == context.invocation.run_id
    finally:
        context.close()


def test_context_exposes_complete_service_surface() -> None:
    context = FakeExecutionContext()
    try:
        required = {
            "invocation",
            "mission",
            "scope",
            "entities",
            "processes",
            "workspace",
            "resources",
            "sessions",
            "artifacts",
            "secrets",
            "interactions",
            "checkpoints",
            "events",
            "logger",
            "cancellation",
            "clock",
        }
        assert all(hasattr(context, name) for name in required)
    finally:
        context.close()


def test_invocation_and_mission_views_are_frozen() -> None:
    context = FakeExecutionContext()
    try:
        with pytest.raises(ValidationError):
            context.invocation.operation = "changed"
        with pytest.raises(ValidationError):
            context.mission.name = "changed"
    finally:
        context.close()
