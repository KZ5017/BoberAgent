"""Portable E5-C wiring/accounting tests are NOT active enforcement evidence."""

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from boberagent_contracts import (
    ConfinementFeature,
    DomainRef,
    PreparationPermit,
    PythonProviderOperation,
    PythonRuntimeAuthorityProjection,
    RuntimePreparationSpec,
    preparation_permit_digest,
    preparation_spec_fingerprint,
)
from boberagent_execution_node import ExecutionNode, NodeConfiguration
from boberagent_execution_node.config import ToolConfiguration
from boberagent_execution_node.identity import NodeId
from boberagent_execution_node.persistence import RuntimeDatabase
from boberagent_execution_node.persistence.migrations import current_revision, upgrade_database
from boberagent_execution_node.preparation.resource_models import BudgetCategory, OperationState
from boberagent_execution_node.preparation.resources import PythonResourceRepository
from boberagent_execution_node.preparation.runtime_confinement import (
    LinuxRuntimeConfinementBackend,
    RuntimeConfinementUnavailable,
    _passed,
    _Report,
    _trusted_tool,
    validate_delegation,
)
from boberagent_execution_node.preparation.runtime_confinement_budget import run_budgeted_probe
from boberagent_execution_node.preparation.runtime_confinement_models import (
    ClosedProbe,
    ConfinementCheck,
    ProbeEvidence,
    ProbeLimits,
    RuntimeConfinementConfiguration,
    StopReason,
)
from boberagent_execution_node.preparation.runtime_confinement_store import ConfinementJournal
from boberagent_execution_node.tools import ToolRegistry
from boberagent_sdk.services.cancellation import CancellationService
from plan_test_fixtures import NOW
from python_runtime_test_fixtures import runtime_authority_fixture
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from test_python_resource_ownership import _seed

NATIVE = (
    Path(__file__).parents[1] / "src/boberagent_execution_node/preparation/native/e5_confinement.c"
)


def evidence(probe: ClosedProbe = ClosedProbe.ISOLATION) -> ProbeEvidence:
    return ProbeEvidence(
        operation_id=DomainRef("probe-test"),
        boot_generation=DomainRef("boot-test"),
        probe=probe,
        helper_sha256="1" * 64,
        bubblewrap_sha256="2" * 64,
        kernel="synthetic-NOT-enforcement",
        limits=ProbeLimits(),
        attached_before_exec=True,
        exit_code=0,
        stop_reason=StopReason.EXITED,
        pids_events=0,
        oom_events=0,
        memory_peak=1000,
        process_peak_upper_bound=8,
        duration_milliseconds=100,
        stdout_hex=b"ISOLATION_PASS\n".hex(),
        stderr_hex="",
        group_empty=True,
        passed=True,
    )


def test_closed_configuration_and_tiny_caps() -> None:
    with pytest.raises(ValueError):
        RuntimeConfinementConfiguration(
            delegated_parent=Path("relative"), helper_sha256="1" * 64, bubblewrap_sha256="2" * 64
        )
    for field, value in (
        ("processes", 16),
        ("memory_bytes", 96 * 1024 * 1024),
        ("scratch_bytes", 2 * 1024 * 1024),
        ("output_bytes", 100000),
        ("seconds", 60),
    ):
        with pytest.raises(ValueError):
            ProbeLimits.model_validate({field: value})
    with pytest.raises(ValueError):
        ClosedProbe("arbitrary-command")
    assert not any("python" in operation.value for operation in ClosedProbe)


def test_node_composition_does_not_expose_private_helper_to_sdk_tools(tmp_path: Path) -> None:
    configuration = RuntimeConfinementConfiguration(
        delegated_parent=tmp_path / "operator-parent",
        helper_sha256="1" * 64,
        bubblewrap_sha256="2" * 64,
    )

    async def run() -> None:
        node = ExecutionNode(
            NodeConfiguration.for_runtime_directory(
                tmp_path / "runtime",
                tools={
                    configuration.helper_tool: ToolConfiguration(executable="/usr/bin/false"),
                    configuration.bubblewrap_tool: ToolConfiguration(executable="/usr/bin/false"),
                    "ordinary-tool": ToolConfiguration(executable="/usr/bin/false"),
                },
            ),
            runtime_confinement_configuration=configuration,
        )
        await node.initialize()
        try:
            assert node.runtime_confinement is not None
            with pytest.raises(KeyError):
                node.tools.get(configuration.helper_tool)
            with pytest.raises(KeyError):
                node.tools.get(configuration.bubblewrap_tool)
            assert node.tools.get("ordinary-tool").name == "ordinary-tool"
            assert (
                node.runtime_confinement._tools.get(configuration.helper_tool).name
                == configuration.helper_tool
            )
            assert node.database is not None
            assert ConfinementJournal(node.database).pending() == ()
        finally:
            await node.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize(
    "parent", [Path("/"), Path("/sys/fs/cgroup"), Path("/tmp/fake"), Path("relative")]
)
def test_unconfigured_or_untrusted_delegation_denied(parent: Path) -> None:
    with pytest.raises((RuntimeConfinementUnavailable, OSError)):
        validate_delegation(parent, ProbeLimits())


def test_report_rejects_missing_mechanism_proof_and_preserves_expected_hits() -> None:
    def report(**changes: object) -> _Report:
        return _Report.model_validate(
            {
                "attached": True,
                "empty": True,
                "reason": "EXITED",
                "exit": 0,
                "pids": 0,
                "oom": 0,
                "memory_peak": 1000,
                "milliseconds": 200,
                "stdout": b"ISOLATION_PASS\n".hex(),
                "stderr": "",
                **changes,
            }
        )

    assert _passed(ClosedProbe.ISOLATION, report())
    assert not _passed(ClosedProbe.ISOLATION, report(attached=False))
    assert not _passed(ClosedProbe.ISOLATION, report(empty=False))
    assert not _passed(ClosedProbe.ISOLATION, report(pids=1))
    assert _passed(ClosedProbe.MEMORY, report(oom=1))
    assert not _passed(ClosedProbe.MEMORY, report(oom=1, reason="CLEANUP_FAILED"))
    assert not _passed(ClosedProbe.MEMORY, report())
    assert _passed(ClosedProbe.PIDS, report(pids=1, stdout=b"PIDS_PASS\n".hex()))
    assert not _passed(
        ClosedProbe.PIDS, report(pids=1, stdout=b"PIDS_PASS\n".hex(), reason="CLEANUP_FAILED")
    )
    assert not _passed(ClosedProbe.DESCENDANTS, report(reason="TIMEOUT", stdout=""))
    assert _passed(ClosedProbe.DESCENDANTS, report(stdout=b"DESCENDANTS_STARTED\n".hex()))
    assert not _passed(
        ClosedProbe.DESCENDANTS,
        report(stdout=b"DESCENDANTS_STARTED\n".hex(), empty=False),
    )
    assert not _passed(
        ClosedProbe.DESCENDANTS,
        report(stdout=b"DESCENDANTS_STARTED\n".hex(), exit=1),
    )
    assert _passed(ClosedProbe.OUTPUT, report(reason="OUTPUT"))


def test_journal_upgrade_from_e5b_reopen_history_conflicts_and_recovery(tmp_path: Path) -> None:
    path = tmp_path / "runtime.sqlite3"
    database = RuntimeDatabase(path)
    upgrade_database(database, "0008_python_resource_ownership")
    upgrade_database(database)
    assert current_revision(database) == "0009_runtime_confinement"
    journal = ConfinementJournal(database)
    item = evidence()
    assert (
        journal.begin(
            item.operation_id,
            item.probe,
            item.limits,
            item.boot_generation,
            "host-boot",
            "1" * 64,
            NOW,
        )
        is None
    )
    assert journal.pending() == ((item.operation_id, "host-boot", "1" * 64),)
    with pytest.raises(ValueError, match="already owned"):
        journal.begin(
            item.operation_id,
            item.probe,
            item.limits,
            item.boot_generation,
            "host-boot",
            "1" * 64,
            NOW,
        )
    journal.finish(item, NOW)
    database.close()
    database = RuntimeDatabase(path)
    try:
        journal = ConfinementJournal(database)
        assert (
            journal.begin(
                item.operation_id,
                item.probe,
                item.limits,
                DomainRef("new-boot"),
                "host-boot",
                "1" * 64,
                NOW,
            )
            == item
        )
        with pytest.raises(ValueError, match="conflicting"):
            journal.begin(
                item.operation_id,
                ClosedProbe.MEMORY,
                item.limits,
                item.boot_generation,
                "host-boot",
                "1" * 64,
                NOW,
            )
        with pytest.raises(IntegrityError), database.transaction() as session:
            session.execute(text("UPDATE runtime_confinement_operations SET state='RUNNING'"))
        pending = DomainRef("pending-probe")
        journal.begin(
            pending, item.probe, item.limits, item.boot_generation, "host-boot", "1" * 64, NOW
        )
        journal.interrupt(pending, NOW)
        journal.interrupt(pending, NOW)
        assert journal.pending() == ()
        with pytest.raises(ValueError, match="already owned/interrupted"):
            journal.begin(
                pending, item.probe, item.limits, item.boot_generation, "host-boot", "1" * 64, NOW
            )
    finally:
        database.close()


class FakeBackend:
    """Protocol fixture: never called real confinement or kernel proof."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def run_closed(
        self,
        operation: ClosedProbe,
        operation_id: DomainRef,
        limits: ProbeLimits,
        *,
        cancellation: CancellationService | None = None,
    ) -> ProbeEvidence:
        self.calls += 1
        if self.fail:
            raise RuntimeConfinementUnavailable()
        return evidence(operation).model_copy(
            update={"operation_id": operation_id, "limits": limits}
        )

    async def check(self, requirements: tuple[ConfinementFeature, ...]) -> ConfinementCheck:
        raise AssertionError("not an enforcement proof")

    async def stop_owned(self, operation_id: DomainRef) -> bool:
        return False

    async def reconcile_owned(self) -> int:
        return 0


@pytest.mark.parametrize("fail", [False, True])
def test_durable_ledger_integration(tmp_path: Path, fail: bool) -> None:
    database = RuntimeDatabase(tmp_path / "runtime.sqlite3")
    upgrade_database(database)
    data = runtime_authority_fixture().model_dump(mode="json")
    budgets = data["permit"]["spec"]["budgets"]
    budgets.update(
        max_file_count=1000,
        max_temporary_bytes=5 * 1024 * 1024,
        max_preparation_write_bytes=5 * 1024 * 1024,
        max_processes=16,
        max_captured_output_bytes=4096,
    )
    data["binding"]["spec"]["budgets"] = budgets.copy()
    data["permit"]["spec_sha256"] = preparation_spec_fingerprint(
        RuntimePreparationSpec.model_validate(data["permit"]["spec"])
    )
    data["binding"]["permit_sha256"] = preparation_permit_digest(
        PreparationPermit.model_validate(data["permit"])
    )
    authority = PythonRuntimeAuthorityProjection.model_validate_json(json.dumps(data))
    _seed(database, authority)
    repo = PythonResourceRepository(
        database, node_id="node-test", boot_generation=DomainRef("boot-a"), clock=lambda: NOW
    )
    ref = repo.reserve(authority, principal_id="core-test").resource_ref
    claim = repo.claim(
        ref,
        operation_id=DomainRef("probe-test"),
        operation=PythonProviderOperation.INSPECT_INTERPRETER,
        owner_token=DomainRef("owner-a"),
        principal_id="core-test",
    )
    backend = FakeBackend(fail)
    try:
        if fail:
            with pytest.raises(RuntimeConfinementUnavailable):
                asyncio.run(
                    run_budgeted_probe(backend, repo, claim, ClosedProbe.ISOLATION, ProbeLimits())
                )
            assert repo.operations(ref)[0].state is OperationState.INTERRUPTED
            assert repo.load(ref).state.value == "LOST"
        else:
            assert asyncio.run(
                run_budgeted_probe(backend, repo, claim, ClosedProbe.ISOLATION, ProbeLimits())
            ).passed
            assert repo.operations(ref)[0].state is OperationState.RELEASED
        assert backend.calls == 1
        committed = {b.category: b.committed for b in repo.budget(ref)}
        assert committed[BudgetCategory.WRITE_BYTES] >= 2 * 1024 * 1024
        assert repo.load(ref).validity.value == "UNCHECKED"
        assert repo.load(ref).state.value != "READY"
        assert not any(b.held for b in repo.budget(ref))
    finally:
        database.close()


def test_trusted_native_helper_build_and_closed_dispatch(tmp_path: Path) -> None:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("trusted C fixture toolchain unavailable; not live enforcement evidence")
    helper = tmp_path / "helper"
    subprocess.run(
        [compiler, "-static", "-O2", "-Wall", "-Wextra", "-Werror", "-o", str(helper), str(NATIVE)],
        check=True,
        timeout=30,
        capture_output=True,
    )
    result = subprocess.run([str(helper), "--identity"], check=True, timeout=3, capture_output=True)
    assert result.stdout == b"m20-e5-linux-bwrap-cgroup@1:static-helper-v1\n"
    assert (
        subprocess.run([str(helper), "arbitrary", "sh"], timeout=3, capture_output=True).returncode
        == 90
    )
    assert hashlib.sha256(helper.read_bytes()).hexdigest()


def test_backend_closed_negative_path_and_restart_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real trusted supervisor with fake control files and /usr/bin/false.

    This is deliberately NEGATIVE wiring evidence, never a cgroup/namespace proof.
    No fixture payload (fork/allocation/mount) is launched by false.
    """
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("static trusted helper toolchain absent")
    helper = tmp_path / "helper"
    subprocess.run(
        [compiler, "-static", "-O2", "-Wall", "-Wextra", "-Werror", "-o", str(helper), str(NATIVE)],
        check=True,
        timeout=30,
        capture_output=True,
    )
    parent = tmp_path / "fake-controls-NOT-cgroup"
    parent.mkdir()
    configuration = RuntimeConfinementConfiguration(
        delegated_parent=parent,
        helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),
        bubblewrap_sha256=hashlib.sha256(Path("/usr/bin/false").read_bytes()).hexdigest(),
    )
    database = RuntimeDatabase(tmp_path / "runtime.sqlite3")
    upgrade_database(database)
    # Fake only the kernel filesystem materialization/delegation. Static helper,
    # barrier/report serialization and controller/journal code really execute.
    monkeypatch.setattr(
        "boberagent_execution_node.preparation.runtime_confinement.validate_delegation",
        lambda *_args: None,
    )
    mkdir = Path.mkdir

    def fake_kernel_mkdir(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        mkdir(path, mode, parents, exist_ok)
        if path.parent == parent:
            for name, content in {
                "cgroup.type": "domain",
                "cgroup.procs": "",
                "cgroup.events": "populated 0",
                "pids.events": "max 0",
                "memory.events": "oom_kill 0",
                "memory.peak": "0",
                "cgroup.kill": "",
            }.items():
                (path / name).write_text(content)

    # Explicit typed signature below avoids a generic production filesystem adapter.
    monkeypatch.setattr(Path, "mkdir", fake_kernel_mkdir)

    def fake_remove(_backend: LinuxRuntimeConfinementBackend, group: Path) -> None:
        for file in group.iterdir():
            file.unlink()
        group.rmdir()

    monkeypatch.setattr(LinuxRuntimeConfinementBackend, "_remove_group", fake_remove)

    async def run() -> None:
        tools = ToolRegistry()
        tools.register(configuration.helper_tool, ToolConfiguration(executable=str(helper)))
        tools.register(
            configuration.bubblewrap_tool, ToolConfiguration(executable="/usr/bin/false")
        )
        await tools.refresh()
        assert (
            _trusted_tool(
                tools, configuration.helper_tool, configuration.helper_sha256, static_elf=True
            )
            == helper
        )
        with pytest.raises(RuntimeConfinementUnavailable):
            _trusted_tool(tools, configuration.helper_tool, "0" * 64, static_elf=True)
        backend = LinuxRuntimeConfinementBackend(
            configuration=configuration,
            node_id=NodeId("node-e5-test"),
            tools=tools,
            database=database,
            runtime_directory=tmp_path,
            boot_generation=DomainRef("boot-a"),
        )
        result = await backend.run_closed(
            ClosedProbe.ISOLATION, DomainRef("probe-negative"), ProbeLimits()
        )
        assert not result.passed
        assert result.attached_before_exec and result.group_empty
        assert result.exit_code == 1
        assert (
            await backend.run_closed(
                ClosedProbe.ISOLATION, DomainRef("probe-negative"), ProbeLimits()
            )
            == result
        )
        assert not await backend.stop_owned(DomainRef("unknown-operation"))
        ready_operation = DomainRef("ready-cancellation")
        read_fd, write_fd = os.pipe()
        backend._active[str(ready_operation)] = write_fd
        try:
            stream = asyncio.StreamReader()
            stream.feed_data(b"ATTACHED\nDESCENDANTS_READY\n")
            stream.feed_eof()
            assert await backend._cancel_ready(ready_operation, stream) == b"ATTACHED\n"
            assert os.read(read_fd, 1) == b"C"
            missing = asyncio.StreamReader()
            missing.feed_data(b"ATTACHED\n")
            missing.feed_eof()
            with pytest.raises(RuntimeConfinementUnavailable):
                await backend._cancel_ready(ready_operation, missing)
        finally:
            backend._active.pop(str(ready_operation))
            os.close(read_fd)
            os.close(write_fd)
        other_node = LinuxRuntimeConfinementBackend(
            configuration=configuration,
            node_id=NodeId("node-e5-other"),
            tools=tools,
            database=database,
            runtime_directory=tmp_path,
            boot_generation=DomainRef("boot-a"),
        )
        assert other_node._group(DomainRef("probe-negative")) != backend._group(
            DomainRef("probe-negative")
        )
        # ':' is valid in logical refs: a textual delimiter alone is ambiguous.
        other_node._node_id = NodeId("node-e5-test:suffix")
        assert other_node._group(DomainRef("operation")) != backend._group(
            DomainRef("suffix:operation")
        )
        collision = DomainRef("pre-existing-group")
        collision_group = backend._group(collision)
        collision_group.mkdir()
        with pytest.raises(FileExistsError):
            await backend.run_closed(ClosedProbe.ISOLATION, collision, ProbeLimits())
        # Refusal must not kill/remove a group this invocation did not create.
        assert (collision_group / "cgroup.kill").read_text() == ""
        fake_remove(backend, collision_group)
        journal = ConfinementJournal(database)
        abandoned = DomainRef("abandoned")
        journal.begin(
            abandoned,
            ClosedProbe.ISOLATION,
            ProbeLimits(),
            DomainRef("old-boot"),
            backend._host_boot(),
            backend._parent_pin(),
            NOW,
        )
        group = backend._group(abandoned)
        group.mkdir()
        assert await backend.reconcile_owned() == 1
        assert not group.exists()
        assert journal.pending() == ()
        # Changed boot never kills a possibly reused group. A changed delegation
        # on the SAME boot fails closed and preserves pending ownership instead.
        previous_boot = DomainRef("previous-host-boot")
        journal.begin(
            previous_boot,
            ClosedProbe.ISOLATION,
            ProbeLimits(),
            DomainRef("old-boot"),
            "different-host-boot",
            backend._parent_pin(),
            NOW,
        )
        await backend.reconcile_owned()
        incompatible = DomainRef("changed-parent")
        journal.begin(
            incompatible,
            ClosedProbe.ISOLATION,
            ProbeLimits(),
            DomainRef("old-boot"),
            backend._host_boot(),
            "0" * 64,
            NOW,
        )
        with pytest.raises(RuntimeConfinementUnavailable):
            await backend.reconcile_owned()
        assert journal.pending()[0][0] == incompatible
        journal.interrupt(incompatible, NOW)
        await backend.shutdown()

    try:
        asyncio.run(run())
    finally:
        database.close()
