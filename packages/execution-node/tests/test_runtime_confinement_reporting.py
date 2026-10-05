"""Real native reporting/descendant wiring with SIMULATED kernel controls.

These offline tests are NOT cgroup/namespace enforcement acceptance. The real
13-probe opt-in harness remains mandatory on the explicitly delegated host.
"""

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
from pathlib import Path

import pytest
from boberagent_contracts import ConfinementFeature, DomainRef, PythonRuntimeReason
from boberagent_execution_node.config import ToolConfiguration
from boberagent_execution_node.identity import NodeId
from boberagent_execution_node.persistence import RuntimeDatabase
from boberagent_execution_node.persistence.migrations import upgrade_database
from boberagent_execution_node.preparation.runtime_confinement import (
    LinuxRuntimeConfinementBackend,
    RuntimeConfinementUnavailable,
    _completed_proof,
    _decode_report,
)
from boberagent_execution_node.preparation.runtime_confinement_models import (
    ClosedProbe,
    ConfinementFailureStage,
    ProbeLimits,
    RuntimeConfinementConfiguration,
    StopReason,
)
from boberagent_execution_node.preparation.runtime_confinement_store import ConfinementJournal
from boberagent_execution_node.tools import ToolRegistry
from test_runtime_confinement import evidence

NATIVE = (
    Path(__file__).parents[1] / "src/boberagent_execution_node/preparation/native/e5_confinement.c"
)
PAYLOAD = Path(__file__).parent / "fixtures/confinement_report_payload.c"


def valid_report(**changes: object) -> bytes:
    return (
        b"ATTACHED\n"
        + json.dumps(
            {
                "attached": True,
                "empty": True,
                "reason": "OWNER_LOST",
                "exit": 137,
                "pids": 0,
                "oom": 0,
                "memory_peak": 1000,
                "milliseconds": 100,
                "stdout": b"DESCENDANTS_STARTED\n".hex(),
                "stderr": "",
                **changes,
            }
        ).encode()
    )


@pytest.mark.parametrize(
    "wire",
    [
        b"",
        b"ATTACHED\n",
        b'ATTACHED\n{"attached":true',
        b'ATTACHED\n{"private":"synthetic-sensitive-canary"}',
        valid_report(attached="true"),
        valid_report(pids="0"),
        valid_report(oom=-1),
        valid_report(stdout="zz"),
        valid_report(stdout="a"),
        valid_report(reason="unknown"),
        valid_report(stderr="00" * 4096),
        valid_report(attached=False),
        b"x" * 20001,
    ],
)
def test_invalid_reports_are_typed_closed_diagnostics(wire: bytes) -> None:
    with pytest.raises(RuntimeConfinementUnavailable) as failure:
        _decode_report(wire, ClosedProbe.REQUESTER_DEATH, ProbeLimits())
    error = failure.value
    assert error.failure.runtime_reason is PythonRuntimeReason.DESCENDANT_CONTAINMENT_UNAVAILABLE
    assert error.probe is ClosedProbe.REQUESTER_DEATH
    assert error.stage is ConfinementFailureStage.REPORT_OR_CLEANUP
    assert str(error) == "DESCENDANT_CONTAINMENT_UNAVAILABLE"
    assert "synthetic-sensitive-canary" not in str(error)
    assert error.__suppress_context__  # raw validation input never appears in a traceback


def test_requester_signal_alone_is_not_a_positive_proof() -> None:
    limits = ProbeLimits()
    probe = ClosedProbe.REQUESTER_DEATH
    report = _decode_report(valid_report(), probe, limits)
    assert _completed_proof(probe, report, returncode=-9, empty=True, limits=limits)
    assert not _completed_proof(probe, report, returncode=0, empty=True, limits=limits)
    assert not _completed_proof(probe, report, returncode=-9, empty=False, limits=limits)
    for changes in (
        {"stdout": ""},
        {"reason": "CLEANUP_FAILED"},
        {"empty": False},
        {"pids": 1},
        {"oom": 1},
        {"memory_peak": limits.memory_bytes + 1},
        {"milliseconds": (limits.seconds + 4) * 1000 + 1},
    ):
        report = _decode_report(valid_report(**changes), probe, limits)
        assert not _completed_proof(probe, report, returncode=-9, empty=True, limits=limits)


def test_check_still_requires_all_thirteen_and_identifies_failed_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No host backend setup/work; only the orchestration contract of check().
    backend = object.__new__(LinuxRuntimeConfinementBackend)
    calls: list[ClosedProbe] = []

    async def run_closed(
        _self: LinuxRuntimeConfinementBackend,
        probe: ClosedProbe,
        _operation: DomainRef,
        _limits: ProbeLimits,
    ) -> object:
        calls.append(probe)
        return evidence(probe)

    monkeypatch.setattr(LinuxRuntimeConfinementBackend, "run_closed", run_closed)
    proof = asyncio.run(backend.check(tuple(ConfinementFeature)))
    assert calls == list(ClosedProbe) and len(proof.probes) == 13

    async def broken(
        _self: LinuxRuntimeConfinementBackend,
        probe: ClosedProbe,
        _operation: DomainRef,
        _limits: ProbeLimits,
    ) -> object:
        if probe is ClosedProbe.REQUESTER_DEATH:
            _decode_report(b"ATTACHED\n", probe, ProbeLimits())
        return evidence(probe)

    monkeypatch.setattr(LinuxRuntimeConfinementBackend, "run_closed", broken)
    with pytest.raises(RuntimeConfinementUnavailable) as failure:
        asyncio.run(backend.check(tuple(ConfinementFeature)))
    assert failure.value.probe is ClosedProbe.REQUESTER_DEATH
    assert failure.value.stage is ConfinementFailureStage.REPORT_OR_CLEANUP


@pytest.mark.parametrize(
    "fault", ["none", "early_requester", "supervisor", "supervisor_probe", "supervisor_early"]
)
def test_native_independent_report_and_owned_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    compiler = shutil.which("cc")
    if compiler is None or not Path("/proc/self").exists():
        pytest.skip("Linux C toolchain required for native wiring regression")
    helper, payload = tmp_path / "helper", tmp_path / "payload"
    for source, output in ((NATIVE, helper), (PAYLOAD, payload)):
        subprocess.run(
            [
                compiler,
                "-static",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-o",
                str(output),
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    parent = tmp_path / "SIMULATED-controls"
    parent.mkdir()
    database = RuntimeDatabase(tmp_path / "runtime.sqlite3")
    upgrade_database(database)
    configuration = RuntimeConfinementConfiguration(
        delegated_parent=parent,
        helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),
        bubblewrap_sha256=hashlib.sha256(payload.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        "boberagent_execution_node.preparation.runtime_confinement.validate_delegation",
        lambda *_args: None,
    )
    mkdir = Path.mkdir

    def simulated_mkdir(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        mkdir(path, mode, parents, exist_ok)
        if path.parent == parent:
            for name, value in {
                "cgroup.type": "domain",
                "cgroup.procs": "",
                "cgroup.events": "populated 0",
                "pids.events": "max 0",
                "memory.events": "oom_kill 0",
                "memory.peak": "1000",
                "cgroup.kill": "",
            }.items():
                (path / name).write_text(value)

    monkeypatch.setattr(Path, "mkdir", simulated_mkdir)
    # Retain only our explicitly owned temporary control files for assertions.
    monkeypatch.setattr(LinuxRuntimeConfinementBackend, "_remove_group", lambda *_args: None)
    spawned: list[asyncio.subprocess.Process] = []
    spawn = asyncio.create_subprocess_exec

    # Capture the requester without a production fault-injection API.
    async def capture_spawn(
        *args: str,
        stdin: int,
        stdout: int,
        stderr: int,
        pass_fds: tuple[int, ...],
        start_new_session: bool,
        cwd: Path,
        env: dict[str, str],
    ) -> asyncio.subprocess.Process:
        process = await spawn(
            *args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            pass_fds=pass_fds,
            start_new_session=start_new_session,
            cwd=cwd,
            env=env,
        )
        spawned.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture_spawn)

    async def run() -> None:
        tools = ToolRegistry()
        tools.register(configuration.helper_tool, ToolConfiguration(executable=str(helper)))
        tools.register(configuration.bubblewrap_tool, ToolConfiguration(executable=str(payload)))
        await tools.refresh()
        backend = LinuxRuntimeConfinementBackend(
            configuration=configuration,
            node_id=NodeId("node-report-test"),
            tools=tools,
            database=database,
            runtime_directory=tmp_path,
            boot_generation=DomainRef("boot-test"),
        )
        probe = (
            ClosedProbe.SUPERVISOR_DEATH
            if fault in {"supervisor_probe", "supervisor_early"}
            else ClosedProbe.REQUESTER_DEATH
        )
        operation = DomainRef(f"report-{fault}")
        group = backend._group(operation)
        cleaned = asyncio.Event()

        async def simulated_kernel() -> tuple[int, int, int, int]:
            async with asyncio.timeout(8):
                while not (group / "test-descendants").exists():
                    await asyncio.sleep(0.001)
                while len(pids := (group / "test-descendants").read_text().split()) != 4:
                    await asyncio.sleep(0.001)
                root, supervisor, child, grandchild = map(int, pids)
                # Both descendants really exist before any readiness/death signal.
                assert Path(f"/proc/{child}").exists() and Path(f"/proc/{grandchild}").exists()
                (group / "cgroup.events").write_text("populated 1")
                (group / "cgroup.kill").write_text("")
                if fault == "early_requester":
                    os.kill(spawned[0].pid, signal.SIGKILL)
                elif fault in {"supervisor", "supervisor_early"}:
                    os.kill(supervisor, signal.SIGKILL)
                else:
                    (group / "test-start").touch()
                while not (group / "cgroup.kill").read_text().strip():
                    await asyncio.sleep(0.001)
                # The actual supervisor/independent guardian requested exact-group
                # cleanup. Emulate kernel kill with orderly test-descendant reaping.
                os.kill(root, signal.SIGTERM)
                while Path(f"/proc/{child}").exists() or Path(f"/proc/{grandchild}").exists():
                    await asyncio.sleep(0.001)
                (group / "cgroup.events").write_text("populated 0")
                cleaned.set()
                return root, supervisor, child, grandchild

        monitor = asyncio.create_task(simulated_kernel())
        try:
            if fault in {"supervisor", "supervisor_early"}:
                with pytest.raises(RuntimeConfinementUnavailable) as failure:
                    await backend.run_closed(probe, operation, ProbeLimits())
                assert failure.value.probe is probe
                assert failure.value.stage is ConfinementFailureStage.REPORT_OR_CLEANUP
                assert cleaned.is_set()  # guardian cleanup preceded report rejection
                assert ConfinementJournal(database).pending() == ()
            else:
                result = await backend.run_closed(probe, operation, ProbeLimits())
                assert result.group_empty and result.attached_before_exec
                assert not result.pids_events and not result.oom_events
                if fault == "none":
                    assert spawned[0].returncode == -signal.SIGKILL
                    assert result.requester_exit_code == -signal.SIGKILL
                    assert result.stop_reason is StopReason.OWNER_LOST
                    assert bytes.fromhex(result.stdout_hex).startswith(b"DESCENDANTS_STARTED\n")
                    assert result.passed
                elif fault == "early_requester":
                    assert spawned[0].returncode == -signal.SIGKILL
                    assert not result.passed and not result.stdout_hex
                else:
                    assert spawned[0].returncode == -signal.SIGKILL
                    assert result.stop_reason is StopReason.SUPERVISOR_LOST and result.passed
            await monitor
            assert cleaned.is_set()
            assert (group / "cgroup.events").read_text() == "populated 0"
        finally:
            if not monitor.done():
                monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        database.close()


def test_manual_harness_failure_is_closed_and_probe_specific(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = Path(__file__).parents[3] / "scripts/manual-smoke/m20e5c_confinement_smoke_test.py"
    spec = importlib.util.spec_from_file_location("confinement_manual_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stopped: list[bool] = []

    class FailedBackend:
        async def check(self, _features: tuple[ConfinementFeature, ...]) -> None:
            _decode_report(
                b'{"sensitive":"synthetic-sensitive-canary"}',
                ClosedProbe.REQUESTER_DEATH,
                ProbeLimits(),
            )

    class LocalNodeFixture:
        runtime_confinement = FailedBackend()

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def initialize(self) -> None:
            pass

        async def shutdown(self) -> None:
            stopped.append(True)

    monkeypatch.setattr(module, "ExecutionNode", LocalNodeFixture)
    # This test exercises report diagnostics, not filesystem preflight (covered separately).
    monkeypatch.setattr(module, "_require_helper_filesystem", lambda _path: None)
    args = argparse.Namespace(
        node_runtime_directory=tmp_path / "runtime",
        delegated_cgroup_parent=tmp_path / "controls",
        helper_sha256="1" * 64,
        bubblewrap_sha256="2" * 64,
        trusted_helper=tmp_path / "helper",
        bubblewrap=tmp_path / "bwrap",
    )
    assert asyncio.run(module.run(args)) == 1
    output = capsys.readouterr()
    assert not output.err and stopped == [True]
    assert json.loads(output.out) == {
        "profile": "m20-e5-linux-bwrap-cgroup@1",
        "result": "FAIL",
        "probe": "requester_death",
        "reason": "DESCENDANT_CONTAINMENT_UNAVAILABLE",
        "stage": "report_or_cleanup",
        "runtime": "UNAVAILABLE",
        "ready": False,
    }
    assert "synthetic-sensitive-canary" not in output.out
