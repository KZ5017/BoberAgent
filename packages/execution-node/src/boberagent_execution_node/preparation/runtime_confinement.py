"""Closed E5-C probes and the E5-D fixed identity, never a generic process API.

The statically linked reviewed helper owns deadlines, concurrent pipe caps, the
attach barrier, a separate death guardian and exact-subtree cleanup. Python is
only the Node control plane for C; D launches only statically verified trusted
CPython with one constant identity program, never a caller/source payload.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import platform
import socket
import stat
import struct
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from boberagent_contracts import (
    ConfinementFeature,
    DomainRef,
    PreparationReasonCode,
    PythonRuntimeFailure,
    PythonRuntimeReason,
)
from boberagent_contracts.python_runtime import RuntimeCorrelation
from boberagent_sdk.services.cancellation import CancellationService
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..identity import NodeId
from ..persistence.database import RuntimeDatabase
from ..tools import ToolAvailability, ToolRegistry
from .python_distribution import PythonDistributionConfiguration, inventory
from .runtime_confinement_models import (
    ClosedProbe,
    ConfinementCheck,
    ConfinementFailureStage,
    ProbeEvidence,
    ProbeLimits,
    RuntimeConfinementConfiguration,
    StopReason,
    TrustedPythonOperation,
)

PROFILE = "m20-e5-linux-bwrap-cgroup@1"


class RuntimeConfinementUnavailable(RuntimeError):
    def __init__(
        self,
        detail: PythonRuntimeReason | None = None,
        *,
        probe: ClosedProbe | TrustedPythonOperation | None = None,
        stage: ConfinementFailureStage | None = None,
    ) -> None:
        self.probe = probe
        self.stage = stage
        self.failure = PythonRuntimeFailure(
            reason_code=PreparationReasonCode.CONFINEMENT_UNAVAILABLE,
            runtime_reason=detail,
        )
        # Closed codes only: no raw host path, subprocess stderr or environment.
        super().__init__(detail.value if detail else "CONFINEMENT_UNAVAILABLE")


class RuntimeConfinementBackend(Protocol):
    async def check(self, requirements: tuple[ConfinementFeature, ...]) -> ConfinementCheck: ...

    async def run_closed(
        self,
        operation: ClosedProbe,
        operation_id: RuntimeCorrelation,
        limits: ProbeLimits,
        *,
        cancellation: CancellationService | None = None,
    ) -> ProbeEvidence: ...

    async def stop_owned(self, operation_id: RuntimeCorrelation) -> bool: ...

    async def reconcile_owned(self) -> int: ...


class _Report(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attached: bool = Field(strict=True)
    empty: bool = Field(strict=True)
    reason: StopReason
    exit: int = Field(strict=True)
    pids: int = Field(ge=0, strict=True)
    oom: int = Field(ge=0, strict=True)
    memory_peak: int = Field(ge=0, strict=True)
    milliseconds: int = Field(ge=0, strict=True)
    stdout: str = Field(max_length=8192, pattern=r"^(?:[0-9a-f]{2})*$", strict=True)
    stderr: str = Field(max_length=8192, pattern=r"^(?:[0-9a-f]{2})*$", strict=True)


def _decode_report(
    data: bytes, probe: ClosedProbe | TrustedPythonOperation, limits: ProbeLimits
) -> _Report:
    """Closed bounded wire evidence; never expose Pydantic's raw input diagnostics."""
    try:
        if len(data) > 20000:
            raise ValueError("report bound")
        report = _Report.model_validate_json(data.removeprefix(b"ATTACHED\n"))
        if (
            report.attached != data.startswith(b"ATTACHED\n")
            or (len(report.stdout) + len(report.stderr)) // 2 > limits.output_bytes
        ):
            raise ValueError("inconsistent report")
        return report
    except (ValidationError, ValueError):
        raise RuntimeConfinementUnavailable(
            _detail(probe), probe=probe, stage=ConfinementFailureStage.REPORT_OR_CLEANUP
        ) from None


def _completed_proof(
    probe: ClosedProbe | TrustedPythonOperation,
    report: _Report,
    *,
    returncode: int | None,
    empty: bool,
    limits: ProbeLimits,
) -> bool:
    return (
        empty
        and _passed(probe, report)
        and report.milliseconds <= (limits.seconds + 4) * 1000
        # Death alone is never proof: _passed also requires readiness, independent
        # OWNER_LOST cleanup, empty group and the expected kernel counters.
        and (probe is not ClosedProbe.REQUESTER_DEATH or returncode == -9)
    )


def _read(path: Path) -> str:
    with path.open("r", encoding="ascii") as stream:
        result = stream.read(4097)
    if len(result) > 4096:
        raise RuntimeConfinementUnavailable()
    return result.strip()


def _events(path: Path) -> dict[str, int]:
    return {key: int(value) for key, value in (line.split() for line in _read(path).splitlines())}


def _no_symlink_components(path: Path) -> None:
    for part in (path, *path.parents):
        if stat.S_ISLNK(part.lstat().st_mode):
            raise RuntimeConfinementUnavailable()


def validate_delegation(parent: Path, limits: ProbeLimits) -> None:
    """Read-only validation; never enable controllers or change parent ownership."""
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeConfinementUnavailable()
    root = Path("/sys/fs/cgroup")
    if not parent.is_absolute() or not parent.is_relative_to(root) or parent == root:
        raise RuntimeConfinementUnavailable()
    _no_symlink_components(parent)
    # v2 is proven by mountinfo, not spoofable ordinary files with similar names.
    mounts = Path("/proc/self/mountinfo").read_text().splitlines()
    if not any(line.split()[4] == str(root) and " - cgroup2 " in line for line in mounts):
        raise RuntimeConfinementUnavailable()
    if (
        parent.stat().st_uid != os.getuid()
        or not os.access(parent, os.W_OK | os.X_OK)
        or _read(parent / "cgroup.type") != "domain"
        or _read(parent / "cgroup.procs")
        or not {"memory", "pids"} <= set(_read(parent / "cgroup.controllers").split())
        or not {"memory", "pids"} <= set(_read(parent / "cgroup.subtree_control").split())
    ):
        raise RuntimeConfinementUnavailable()
    # A stricter ancestor would invalidate the configured active probe semantics.
    for ancestor in (parent, *parent.parents):
        if not ancestor.is_relative_to(root):
            break
        for name, wanted, detail in (
            ("pids.max", limits.processes + 3, PythonRuntimeReason.PROCESS_LIMIT_UNAVAILABLE),
            (
                "memory.max",
                limits.memory_bytes + 8 * 1024 * 1024,
                PythonRuntimeReason.MEMORY_LIMIT_UNAVAILABLE,
            ),
        ):
            path = ancestor / name
            if path.exists() and (value := _read(path)) != "max":
                current = ancestor / name.replace(".max", ".current")
                if not current.exists() or int(value) - int(_read(current)) < wanted:
                    raise RuntimeConfinementUnavailable(detail)


def _trusted_tool(tools: ToolRegistry, name: str, digest: str, *, static_elf: bool) -> Path:
    record = tools.get(name)
    path = record.resolved_path
    if record.availability != ToolAvailability.AVAILABLE or path is None:
        raise RuntimeConfinementUnavailable()
    configured = Path(record.configured_executable)
    if not configured.is_absolute() or configured != path:
        raise RuntimeConfinementUnavailable()
    _no_symlink_components(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o6022 or not info.st_mode & 0o111:
        raise RuntimeConfinementUnavailable()
    # Explicit operator trust plus byte pinning; no claim against malicious same-UID admin.
    if info.st_uid not in {0, os.getuid()}:
        raise RuntimeConfinementUnavailable()
    for directory in path.parents:
        if directory.stat().st_mode & 0o022 and not directory.stat().st_mode & stat.S_ISVTX:
            raise RuntimeConfinementUnavailable()
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise RuntimeConfinementUnavailable()
        if static_elf:
            stream.seek(0)
            header = stream.read(64)
            if (
                len(header) != 64
                or header[:6] != b"\x7fELF\x02\x01"
                or struct.unpack_from("<H", header, 18)[0] != 62
            ):
                raise RuntimeConfinementUnavailable()
            offset = struct.unpack_from("<Q", header, 32)[0]
            width, count = struct.unpack_from("<HH", header, 54)
            if width != 56 or not 1 <= count <= 128:
                raise RuntimeConfinementUnavailable()
            stream.seek(offset)
            for _ in range(count):
                segment = stream.read(width)
                if len(segment) != width or struct.unpack_from("<I", segment)[0] == 3:
                    raise RuntimeConfinementUnavailable()
    return path


def _passed(probe: ClosedProbe | TrustedPythonOperation, report: _Report) -> bool:
    if not report.attached or not report.empty or report.memory_peak > 64 * 1024 * 1024:
        return False
    marker = bytes.fromhex(report.stdout)
    if probe is TrustedPythonOperation.IDENTITY:
        return (
            report.reason is StopReason.EXITED
            and report.exit == 0
            and not report.pids
            and not report.oom
        )
    if probe is ClosedProbe.PIDS:
        return (
            report.pids > 0
            and report.oom == 0
            and b"PIDS_PASS\n" in marker
            and report.reason in {StopReason.EXITED, StopReason.TIMEOUT}
        )
    if probe is ClosedProbe.MEMORY:
        return report.oom > 0 and report.pids == 0 and report.reason is StopReason.EXITED
    if report.pids or report.oom:
        return False
    if probe in {ClosedProbe.ISOLATION, ClosedProbe.BYTES, ClosedProbe.INODES}:
        return (
            report.reason is StopReason.EXITED
            and report.exit == 0
            and marker
            == {
                ClosedProbe.ISOLATION: b"ISOLATION_PASS\n",
                ClosedProbe.BYTES: b"BYTES_PASS\n",
                ClosedProbe.INODES: b"INODES_PASS\n",
            }[probe]
        )
    if probe is ClosedProbe.OUTPUT:
        return report.reason is StopReason.OUTPUT
    if probe is ClosedProbe.CANCEL:
        return report.reason is StopReason.CANCELLED and b"DESCENDANTS_STARTED\n" in marker
    if probe is ClosedProbe.REQUESTER_DEATH:
        return report.reason is StopReason.OWNER_LOST and b"DESCENDANTS_STARTED\n" in marker
    if probe in {ClosedProbe.DESCENDANTS, ClosedProbe.SETSID, ClosedProbe.DOUBLE_FORK}:
        # A wrapper may return when the fixture leader exits; alternatively its
        # inherited descendant pipes stay open until our deadline. Either path
        # must still kill the EXACT group and prove it empty, never infer this
        # solely from the direct child's exit status.
        return b"DESCENDANTS_STARTED\n" in marker and (
            report.reason is StopReason.TIMEOUT
            or (report.reason is StopReason.EXITED and report.exit == 0)
        )
    return report.reason is StopReason.TIMEOUT


class LinuxRuntimeConfinementBackend:
    """Explicit configured host backend. No preparation transport/provider wiring."""

    def __init__(
        self,
        *,
        configuration: RuntimeConfinementConfiguration,
        node_id: NodeId,
        tools: ToolRegistry,
        database: RuntimeDatabase,
        runtime_directory: Path,
        boot_generation: RuntimeCorrelation,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.configuration = configuration
        self._node_id = node_id
        self._tools = tools
        self._database = database
        self._root = runtime_directory
        self._boot = boot_generation
        self._clock = clock
        self._active: dict[str, int] = {}
        self._finished: dict[str, asyncio.Event] = {}

    def _group(self, operation_id: RuntimeCorrelation) -> Path:
        return self.configuration.delegated_parent / (
            "bober-e5-"
            + hashlib.sha256(
                str(self._node_id).encode() + b"\0" + str(operation_id).encode()
            ).hexdigest()
        )

    def _host_boot(self) -> str:
        return _read(Path("/proc/sys/kernel/random/boot_id"))

    def _parent_pin(self) -> str:
        parent = self.configuration.delegated_parent
        info = parent.stat()
        return hashlib.sha256(f"{parent}:{info.st_dev}:{info.st_ino}".encode()).hexdigest()

    async def check(self, requirements: tuple[ConfinementFeature, ...]) -> ConfinementCheck:
        if set(requirements) != set(ConfinementFeature) or len(requirements) != len(
            ConfinementFeature
        ):
            raise RuntimeConfinementUnavailable()
        evidence = []
        for probe in ClosedProbe:
            try:
                result = await self.run_closed(
                    probe, DomainRef(f"confinement-{uuid4()}"), ProbeLimits()
                )
            except RuntimeConfinementUnavailable as error:
                raise RuntimeConfinementUnavailable(
                    error.failure.runtime_reason or _detail(probe),
                    probe=probe,
                    stage=error.stage or ConfinementFailureStage.REPORT_OR_CLEANUP,
                ) from None
            evidence.append(result)
            if not result.passed:
                raise RuntimeConfinementUnavailable(
                    _detail(probe), probe=probe, stage=ConfinementFailureStage.PROBE
                )
        return ConfinementCheck(features=tuple(ConfinementFeature), probes=tuple(evidence))

    async def run_closed(
        self,
        operation: ClosedProbe,
        operation_id: RuntimeCorrelation,
        limits: ProbeLimits,
        *,
        cancellation: CancellationService | None = None,
    ) -> ProbeEvidence:
        if not isinstance(operation, ClosedProbe):
            raise ValueError("closed trusted probe required")
        return await self._run_operation(operation, operation_id, limits, cancellation=cancellation)

    async def run_identity(
        self,
        distribution: PythonDistributionConfiguration,
        operation_id: RuntimeCorrelation,
        *,
        cancellation: CancellationService | None = None,
    ) -> ProbeEvidence:
        """Only the fixed -I -S -B identity; explicit pinned operator material first.

        No code, argv, executable, mount or environment parameter from a capability.
        Rehash before and after; historical journal replay is not current integrity.
        """
        before = inventory(distribution)
        result = await self._run_operation(
            TrustedPythonOperation.IDENTITY,
            operation_id,
            ProbeLimits(),
            distribution=distribution,
            cancellation=cancellation,
        )
        if inventory(distribution) != before:
            from .python_distribution import ProvenanceFailure

            raise ProvenanceFailure(PythonRuntimeReason.RUNTIME_INTEGRITY_FAILURE, "post_identity")
        return result

    async def _run_operation(
        self,
        operation: ClosedProbe | TrustedPythonOperation,
        operation_id: RuntimeCorrelation,
        limits: ProbeLimits,
        *,
        distribution: PythonDistributionConfiguration | None = None,
        cancellation: CancellationService | None = None,
    ) -> ProbeEvidence:
        from .runtime_confinement_store import ConfinementJournal

        if cancellation is not None:
            await cancellation.checkpoint()
        journal = ConfinementJournal(self._database)
        validate_delegation(self.configuration.delegated_parent, limits)
        from .confinement import _trusted_runtime_mounts

        # Preserve reviewed E4 topology checks, but mount no host /usr for the
        # static fixture: none of its contents are needed by this closed probe.
        _trusted_runtime_mounts(Path("/"))
        helper = _trusted_tool(
            self._tools,
            self.configuration.helper_tool,
            self.configuration.helper_sha256,
            static_elf=True,
        )
        bwrap = _trusted_tool(
            self._tools,
            self.configuration.bubblewrap_tool,
            self.configuration.bubblewrap_sha256,
            static_elf=False,
        )
        previous = journal.begin(
            operation_id,
            operation,
            limits,
            self._boot,
            self._host_boot(),
            self._parent_pin(),
            self._clock(),
            input_sha256=inventory(distribution).digest if distribution is not None else None,
        )
        if previous is not None:
            return previous  # historical evidence only; check() always uses fresh identities
        group = self._group(operation_id)
        process: asyncio.subprocess.Process | None = None
        group_created = False
        cancel_monitor: asyncio.Task[None] | None = None
        read_fd, write_fd = os.pipe()
        finished = asyncio.Event()
        self._finished[str(operation_id)] = finished
        try:
            group.mkdir(mode=0o700)
            group_created = True
            if _read(group / "cgroup.type") != "domain" or _read(group / "cgroup.procs"):
                raise RuntimeConfinementUnavailable()
            for name, value in (
                ("pids.max", limits.processes),
                ("memory.max", limits.memory_bytes),
                ("memory.swap.max", 0),
                ("memory.oom.group", 1),
            ):
                (group / name).write_text(f"{value}\n", encoding="ascii")
                if _read(group / name) != str(value):
                    raise RuntimeConfinementUnavailable()
            for name in ("cgroup.kill", "memory.peak", "pids.events", "memory.events"):
                if not (group / name).exists():
                    raise RuntimeConfinementUnavailable()
            if not os.access(group / "cgroup.kill", os.W_OK):
                raise RuntimeConfinementUnavailable(
                    PythonRuntimeReason.DESCENDANT_CONTAINMENT_UNAVAILABLE
                )
            self._root.mkdir(parents=True, exist_ok=True)
            with (
                tempfile.TemporaryDirectory(
                    prefix="e5-trusted-probe-", dir=self._root
                ) as temporary,
                socket.socket() if distribution is None else contextlib.nullcontext() as listener,
            ):
                source = Path(temporary)
                if listener is not None:
                    (source / "sentinel").write_bytes(b"E5_SOURCE\n")
                    listener.bind(("127.0.0.1", 0))
                    listener.listen(1)
                    # Deliberately seed an inherited socket: helper close_range removes it
                    # before bubblewrap. No socket/control descriptor enters the fixture.
                    listener.set_inheritable(True)
                extra: tuple[str, ...] = ()
                if operation is TrustedPythonOperation.IDENTITY:
                    assert distribution is not None
                    manifest = inventory(distribution)
                    source = distribution.distribution_root
                    names = sorted({e.path.split("#")[0] for e in manifest.support_entries})
                    # Every alias is a pinned, one-hop internal regular target.
                    extra = (
                        manifest.schema_version,
                        *(str(distribution.system_library_root / name) for name in names),
                    )
                process = await asyncio.create_subprocess_exec(
                    str(helper),
                    "requester" if operation is ClosedProbe.REQUESTER_DEATH else "supervise",
                    str(bwrap),
                    str(helper),
                    str(source),
                    operation.value,
                    str(limits.processes),
                    str(limits.output_bytes),
                    str(limits.seconds),
                    *extra,
                    stdin=read_fd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    pass_fds=(listener.fileno(),) if listener is not None else (),
                    start_new_session=True,
                    cwd=group,
                    env={
                        "PATH": "/usr/bin:/bin",
                        "LANG": "C",
                        "E5_PROBE_PORT": str(listener.getsockname()[1])
                        if listener is not None
                        else "1",
                    },
                )
                os.close(read_fd)
                read_fd = -1
                self._active[str(operation_id)] = write_fd
                if cancellation is not None:
                    cancel_monitor = asyncio.create_task(
                        self._monitor_cancellation(operation_id, cancellation, finished)
                    )
                assert process.stdout is not None
                prefix = b""
                if operation is ClosedProbe.CANCEL:
                    prefix = await self._cancel_ready(operation_id, process.stdout)
                try:
                    data = await asyncio.wait_for(
                        self._bounded_report(process.stdout), limits.seconds + 8
                    )
                except (TimeoutError, RuntimeConfinementUnavailable):
                    raise RuntimeConfinementUnavailable(
                        _detail(operation),
                        probe=operation,
                        stage=ConfinementFailureStage.REPORT_OR_CLEANUP,
                    ) from None
                data = prefix + data
                await asyncio.wait_for(process.wait(), 3)
                empty = await self._await_empty(group)
                attached = data.startswith(b"ATTACHED\n")
                if operation is ClosedProbe.SUPERVISOR_DEATH and process.returncode == -9:
                    try:
                        if data != b"ATTACHED\nSUPERVISOR_DEATH_READY\n":
                            raise ValueError("missing death readiness proof")
                        report = _Report(
                            attached=attached,
                            empty=empty,
                            reason=StopReason.SUPERVISOR_LOST,
                            exit=137,
                            pids=_events(group / "pids.events")["max"],
                            oom=_events(group / "memory.events")["oom_kill"],
                            memory_peak=int(_read(group / "memory.peak")),
                            milliseconds=limits.seconds * 1000,
                            stdout="",
                            stderr="",
                        )
                    except (ValueError, KeyError, OSError):
                        raise RuntimeConfinementUnavailable(
                            _detail(operation),
                            probe=operation,
                            stage=ConfinementFailureStage.REPORT_OR_CLEANUP,
                        ) from None
                    passed = (
                        attached
                        and empty
                        and not report.pids
                        and not report.oom
                        and report.memory_peak <= limits.memory_bytes
                    )
                else:
                    report = _decode_report(data, operation, limits)
                    passed = _completed_proof(
                        operation, report, returncode=process.returncode, empty=empty, limits=limits
                    )
                result = ProbeEvidence(
                    operation_id=operation_id,
                    boot_generation=self._boot,
                    probe=operation,
                    helper_sha256=self.configuration.helper_sha256,
                    bubblewrap_sha256=self.configuration.bubblewrap_sha256,
                    kernel=platform.release(),
                    limits=limits,
                    attached_before_exec=report.attached,
                    exit_code=report.exit,
                    requester_exit_code=(
                        process.returncode if operation is ClosedProbe.REQUESTER_DEATH else None
                    ),
                    stop_reason=report.reason,
                    pids_events=report.pids,
                    oom_events=report.oom,
                    memory_peak=report.memory_peak,
                    process_peak_upper_bound=limits.processes,
                    duration_milliseconds=report.milliseconds,
                    stdout_hex=report.stdout,
                    stderr_hex=report.stderr,
                    group_empty=empty and report.empty,
                    passed=passed,
                )
                journal.finish(result, self._clock())
                if empty:
                    self._remove_group(group)
                return result
        except BaseException:
            # Closing liveness delegates independent cleanup even on coroutine loss.
            if str(operation_id) in self._active:
                os.close(self._active.pop(str(operation_id)))
                write_fd = -1
            if group_created and group.exists():
                await self._kill_owned_group(group)
            if process is not None:
                await asyncio.wait_for(process.wait(), 8)
            journal.interrupt(operation_id, self._clock())
            raise
        finally:
            if cancel_monitor is not None:
                cancel_monitor.cancel()
                # No service/backend teardown is performed by this small monitor.
                with contextlib.suppress(asyncio.CancelledError):
                    await cancel_monitor
            self._active.pop(str(operation_id), None)
            if read_fd >= 0:
                os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)
            finished.set()
            self._finished.pop(str(operation_id), None)

    async def _bounded_report(self, stream: asyncio.StreamReader) -> bytes:
        data = bytearray()
        while chunk := await stream.read(1024):
            data.extend(chunk)
            if len(data) > 20000:
                raise RuntimeConfinementUnavailable()
        return bytes(data)

    async def shutdown(self) -> None:
        finished = tuple(self._finished.values())
        for operation_id in tuple(self._active):
            await self.stop_owned(DomainRef(operation_id))
        for waiter in finished:
            await asyncio.wait_for(waiter.wait(), 12)
        await self.reconcile_owned()

    async def _monitor_cancellation(
        self,
        operation_id: RuntimeCorrelation,
        cancellation: CancellationService,
        finished: asyncio.Event,
    ) -> None:
        while not finished.is_set():
            if cancellation.requested:
                await self.stop_owned(operation_id)
                return
            await asyncio.sleep(0.025)

    async def _cancel_ready(
        self, operation_id: RuntimeCorrelation, stream: asyncio.StreamReader
    ) -> bytes:
        # Supervisor signals only after the fixture confirms both descendants.
        # No assumed bubblewrap wrapper/process count is used as readiness proof.
        async def ready() -> bytes:
            if await stream.readline() != b"ATTACHED\n":
                raise RuntimeConfinementUnavailable()
            if await stream.readline() != b"DESCENDANTS_READY\n":
                raise RuntimeConfinementUnavailable(
                    PythonRuntimeReason.DESCENDANT_CONTAINMENT_UNAVAILABLE
                )
            return b"ATTACHED\n"

        prefix = await asyncio.wait_for(ready(), 2)
        if not await self.stop_owned(operation_id):
            raise RuntimeConfinementUnavailable(
                PythonRuntimeReason.DESCENDANT_CONTAINMENT_UNAVAILABLE
            )
        return prefix

    async def stop_owned(self, operation_id: RuntimeCorrelation) -> bool:
        if (fd := self._active.get(str(operation_id))) is None:
            return False  # no arbitrary historical caller group kill
        try:
            os.write(fd, b"C")
        except BrokenPipeError:
            return False
        return True

    async def _await_empty(self, group: Path) -> bool:
        end = asyncio.get_running_loop().time() + 3
        while asyncio.get_running_loop().time() < end:
            if _events(group / "cgroup.events")["populated"] == 0:
                return True
            await asyncio.sleep(0.01)
        return False

    async def _kill_owned_group(self, group: Path) -> bool:
        _no_symlink_components(group)
        (group / "cgroup.kill").write_text("1\n", encoding="ascii")
        return await self._await_empty(group)

    async def reconcile_owned(self) -> int:
        from .runtime_confinement_store import ConfinementJournal

        journal = ConfinementJournal(self._database)
        pending = journal.pending()
        for operation_id, host_boot, parent_pin in pending:
            if host_boot != self._host_boot():
                journal.interrupt(operation_id, self._clock())
                continue  # reboot: NEVER kill a reused path/PID
            if parent_pin != self._parent_pin():
                raise RuntimeConfinementUnavailable(
                    PythonRuntimeReason.DESCENDANT_CONTAINMENT_UNAVAILABLE
                )
            group = self._group(operation_id)
            if group.exists():
                if not await self._kill_owned_group(group):
                    raise RuntimeConfinementUnavailable(
                        PythonRuntimeReason.DESCENDANT_CONTAINMENT_UNAVAILABLE
                    )
                self._remove_group(group)
            journal.interrupt(operation_id, self._clock())
        return len(pending)

    def _remove_group(self, group: Path) -> None:
        group.rmdir()  # cgroup pseudo-files disappear with their empty group


def _detail(probe: ClosedProbe | TrustedPythonOperation) -> PythonRuntimeReason | None:
    if probe is ClosedProbe.PIDS:
        return PythonRuntimeReason.PROCESS_LIMIT_UNAVAILABLE
    if probe is ClosedProbe.MEMORY:
        return PythonRuntimeReason.MEMORY_LIMIT_UNAVAILABLE
    if probe in {ClosedProbe.BYTES, ClosedProbe.INODES}:
        return PythonRuntimeReason.STORAGE_LIMIT_UNAVAILABLE
    if probe in {
        ClosedProbe.DESCENDANTS,
        ClosedProbe.SETSID,
        ClosedProbe.DOUBLE_FORK,
        ClosedProbe.REQUESTER_DEATH,
        ClosedProbe.SUPERVISOR_DEATH,
        ClosedProbe.CANCEL,
    }:
        return PythonRuntimeReason.DESCENDANT_CONTAINMENT_UNAVAILABLE
    if probe is ClosedProbe.DEADLINE:
        return PythonRuntimeReason.RUNTIME_LIMIT_UNAVAILABLE
    return None
