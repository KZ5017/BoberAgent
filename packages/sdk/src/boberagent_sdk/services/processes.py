"""Managed process execution interface; no subprocess implementation lives here."""

from __future__ import annotations

from typing import Protocol, Self

from boberagent_contracts import ArtifactRef, ExecutionPlan
from pydantic import BaseModel, ConfigDict, model_validator


class ProcessResult(BaseModel):
    """Bounded result metadata returned by a managed process service."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exit_code: int | None = None
    stdout: bytes = b""
    stderr: bytes = b""
    stdout_artifact_ref: ArtifactRef | None = None
    stderr_artifact_ref: ArtifactRef | None = None
    timed_out: bool = False
    cancelled: bool = False

    @model_validator(mode="after")
    def validate_terminal_flags(self) -> Self:
        if self.timed_out and self.cancelled:
            raise ValueError("a process result cannot be both timed out and cancelled")
        if self.exit_code is None and not (self.timed_out or self.cancelled):
            raise ValueError("exit_code is required unless execution timed out or was cancelled")
        return self

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.cancelled


class ProcessService(Protocol):
    async def run_tool(
        self,
        *,
        tool: str,
        args: list[str] | tuple[str, ...],
        timeout: float | None = None,
    ) -> ProcessResult: ...

    async def execute_plan(
        self,
        *,
        plan: ExecutionPlan,
        timeout: float | None = None,
    ) -> ProcessResult: ...
