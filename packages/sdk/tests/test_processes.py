"""Managed-process expectations and terminal result semantics."""

import asyncio

import pytest
from boberagent_sdk import ProcessResult, ToolExecutionError
from boberagent_sdk.testing import FakeExecutionContext
from pydantic import ValidationError


def test_expected_tool_invocation_succeeds() -> None:
    context = FakeExecutionContext()
    expected = ProcessResult(exit_code=0, stdout=b"structured output")
    context.processes.expect_tool(
        tool="fixture-tool",
        args=["--json", "target.test"],
        timeout=30,
        result=expected,
    )
    try:
        actual = asyncio.run(
            context.processes.run_tool(
                tool="fixture-tool", args=["--json", "target.test"], timeout=30
            )
        )
        assert actual == expected
        assert actual.succeeded
        context.processes.assert_expectations_met()
    finally:
        context.close()


def test_unexpected_tool_invocation_fails_clearly() -> None:
    context = FakeExecutionContext()
    try:
        with pytest.raises(ToolExecutionError, match="Unexpected tool invocation"):
            asyncio.run(context.processes.run_tool(tool="unknown-tool", args=[]))
    finally:
        context.close()


def test_timeout_and_cancellation_are_distinct_process_results() -> None:
    timed_out = ProcessResult(timed_out=True, stderr=b"deadline reached")
    cancelled = ProcessResult(cancelled=True)
    assert timed_out.timed_out and not timed_out.cancelled and not timed_out.succeeded
    assert cancelled.cancelled and not cancelled.timed_out and not cancelled.succeeded
    with pytest.raises(ValidationError):
        ProcessResult(timed_out=True, cancelled=True)
