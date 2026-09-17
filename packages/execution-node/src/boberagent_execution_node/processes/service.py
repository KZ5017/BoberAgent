"""Real asyncio managed-process implementation of the SDK ProcessService."""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from boberagent_contracts import ArtifactRef, CapabilityRunRef, ExecutionPlan
from boberagent_sdk import ExecutionCancelled, PolicyDenied, ProcessResult, ToolExecutionError

from boberagent_execution_node.artifacts import LocalArtifactSpool
from boberagent_execution_node.persistence import ProcessRecord, ProcessState, RuntimeStore
from boberagent_execution_node.tools import ToolAvailability, ToolRegistry


class NodeCancellationService:
    """Per-Run cooperative cancellation signal shared with managed services."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    def request(self) -> None:
        self._event.set()

    async def checkpoint(self) -> None:
        if self.requested:
            raise ExecutionCancelled("CapabilityRun cancellation requested")

    async def wait(self) -> None:
        await self._event.wait()


class ManagedProcessService:
    """Execute registered tools with bounded inline output and durable spillover."""

    def __init__(
        self,
        *,
        tools: ToolRegistry,
        store: RuntimeStore,
        run_ref: CapabilityRunRef,
        cancellation: NodeCancellationService,
        artifacts: LocalArtifactSpool,
        output_root: Path,
        clock: Callable[[], datetime],
        terminate_grace_seconds: float,
        max_inline_output_bytes: int,
    ) -> None:
        self._tools = tools
        self._store = store
        self._run_ref = run_ref
        self._cancellation = cancellation
        self._artifacts = artifacts
        self._output_root = output_root.resolve()
        self._output_root.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._terminate_grace_seconds = terminate_grace_seconds
        self._max_inline_output_bytes = max_inline_output_bytes
        self._active_pids: set[int] = set()

    @property
    def active_pids(self) -> frozenset[int]:
        return frozenset(self._active_pids)

    async def run_tool(
        self,
        *,
        tool: str,
        args: list[str] | tuple[str, ...],
        timeout: float | None = None,
    ) -> ProcessResult:
        await self._cancellation.checkpoint()
        try:
            record = self._tools.get(tool)
        except KeyError as error:
            raise ToolExecutionError(f"unknown managed tool: {tool}") from error
        if record.availability is not ToolAvailability.AVAILABLE or record.resolved_path is None:
            raise ToolExecutionError(f"managed tool is unavailable: {tool}")

        process_id = f"process-{uuid4()}"
        stdout_path = self._output_root / f"{process_id}.stdout"
        stderr_path = self._output_root / f"{process_id}.stderr"
        self._store.add_process(
            ProcessRecord(
                process_id=process_id,
                run_ref=self._run_ref,
                tool=tool,
                state=ProcessState.CREATED,
                argument_count=len(args),
            )
        )
        started_at = self._clock()
        environment = {"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        try:
            with stdout_path.open("xb") as stdout_file, stderr_path.open("xb") as stderr_file:
                process = await asyncio.create_subprocess_exec(
                    str(record.resolved_path),
                    *args,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    env=environment,
                )
                state = await self._wait_for_process(
                    process_id=process_id,
                    process=process,
                    timeout=timeout,
                    started_at=started_at,
                )
        except asyncio.CancelledError:
            stdout_path.unlink(missing_ok=True)
            stderr_path.unlink(missing_ok=True)
            raise
        except OSError as error:
            stdout_path.unlink(missing_ok=True)
            stderr_path.unlink(missing_ok=True)
            self._store.update_process(
                process_id,
                ProcessState.FAILED,
                started_at=started_at,
                finished_at=self._clock(),
            )
            raise ToolExecutionError(f"could not start managed tool: {tool}") from error

        self._store.update_process(
            process_id,
            state,
            finished_at=self._clock(),
            exit_code=process.returncode,
        )
        stdout, stdout_artifact = await self._collect_output(
            path=stdout_path,
            stream="stdout",
            tool=tool,
            process_id=process_id,
        )
        stderr, stderr_artifact = await self._collect_output(
            path=stderr_path,
            stream="stderr",
            tool=tool,
            process_id=process_id,
        )
        if state is ProcessState.CANCELLED:
            return ProcessResult(
                stdout=stdout,
                stderr=stderr,
                stdout_artifact_ref=stdout_artifact,
                stderr_artifact_ref=stderr_artifact,
                cancelled=True,
            )
        if state is ProcessState.TIMED_OUT:
            return ProcessResult(
                stdout=stdout,
                stderr=stderr,
                stdout_artifact_ref=stdout_artifact,
                stderr_artifact_ref=stderr_artifact,
                timed_out=True,
            )
        if process.returncode is None:
            raise ToolExecutionError("managed process exited without a return code")
        return ProcessResult(
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            stdout_artifact_ref=stdout_artifact,
            stderr_artifact_ref=stderr_artifact,
        )

    async def execute_plan(
        self,
        *,
        plan: ExecutionPlan,
        timeout: float | None = None,
    ) -> ProcessResult:
        del plan, timeout
        raise PolicyDenied("ExecutionPlan execution is not implemented in Milestone 4")

    async def _wait_for_process(
        self,
        *,
        process_id: str,
        process: asyncio.subprocess.Process,
        timeout: float | None,
        started_at: datetime,
    ) -> ProcessState:
        self._active_pids.add(process.pid)
        self._store.update_process(
            process_id,
            ProcessState.RUNNING,
            pid=process.pid,
            started_at=started_at,
        )
        completion = asyncio.create_task(process.wait())
        cancellation = asyncio.create_task(self._cancellation.wait())
        try:
            done, _pending = await asyncio.wait(
                {completion, cancellation},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if completion in done:
                completion.result()
                return ProcessState.EXITED
            if cancellation in done:
                await self._terminate(process, completion)
                return ProcessState.CANCELLED
            await self._terminate(process, completion)
            return ProcessState.TIMED_OUT
        except asyncio.CancelledError:
            await self._terminate(process, completion)
            self._store.update_process(
                process_id,
                ProcessState.CANCELLED,
                finished_at=self._clock(),
                exit_code=process.returncode,
            )
            raise
        finally:
            cancellation.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancellation
            self._active_pids.discard(process.pid)

    async def _terminate(
        self,
        process: asyncio.subprocess.Process,
        completion: asyncio.Task[int],
    ) -> None:
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(
                asyncio.shield(completion), timeout=self._terminate_grace_seconds
            )
        except TimeoutError:
            if process.returncode is None:
                process.kill()
            await completion

    async def _collect_output(
        self,
        *,
        path: Path,
        stream: str,
        tool: str,
        process_id: str,
    ) -> tuple[bytes, ArtifactRef | None]:
        try:
            size = path.stat().st_size
            if size <= self._max_inline_output_bytes:
                return path.read_bytes(), None
            descriptor = await self._artifacts.create_from_file(
                artifact_type=f"process.{stream}",
                path=path,
                media_type="application/octet-stream",
                metadata={"tool": tool, "process_id": process_id, "stream": stream},
            )
            return b"", descriptor.artifact_id
        finally:
            path.unlink(missing_ok=True)
