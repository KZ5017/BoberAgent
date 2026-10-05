"""Operator helper-installation prerequisites, without live enforcement probes."""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest
from boberagent_execution_node.preparation.runtime_confinement import RuntimeConfinementUnavailable
from boberagent_execution_node.preparation.runtime_confinement_models import ConfinementFailureStage


@pytest.fixture
def harness() -> ModuleType:
    path = Path(__file__).parents[3] / "scripts/manual-smoke/m20e5c_confinement_smoke_test.py"
    spec = importlib.util.spec_from_file_location("confinement_helper_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tmp_path.chmod(0o755)
    tools = tmp_path / "tools"
    tools.mkdir(mode=0o755)
    tools.chmod(0o755)
    path = tools / "helper-sensitive-path-canary"
    path.write_bytes(b"fixture, not an executable enforcement helper")
    path.chmod(0o755)
    lstat = Path.lstat

    def trusted_fixture_ancestors(directory: Path) -> os.stat_result:
        info = lstat(directory)
        if directory in tmp_path.parents:
            # Simulate trusted higher ancestors: normal pytest runs under sticky
            # writable /tmp, which MUST NOT become an accepted install location.
            values = list(info)
            values[0] = info.st_mode & ~0o022
            return os.stat_result(values)
        return info

    monkeypatch.setattr(Path, "lstat", trusted_fixture_ancestors)
    return path


def test_explicit_0755_helper_and_trusted_parent_chain_pass(
    harness: ModuleType, helper: Path
) -> None:
    harness._require_helper_filesystem(helper)
    assert helper.stat().st_mode & 0o7777 == 0o755


def test_documented_install_modes_do_not_depend_on_umask(harness: ModuleType, helper: Path) -> None:
    install = shutil.which("install")
    if install is None:
        pytest.skip("operator installation utility unavailable")
    directory = helper.parent.parent / "explicit-tools"
    installed = directory / "helper"
    for args in (
        [install, "-d", "-m", "0755", str(directory)],
        [install, "-m", "0755", str(helper), str(installed)],
    ):
        subprocess.run(args, check=True, timeout=3, capture_output=True, umask=0)
    assert directory.stat().st_mode & 0o7777 == 0o755
    assert installed.stat().st_mode & 0o7777 == 0o755
    assert installed.read_bytes() == helper.read_bytes()
    harness._require_helper_filesystem(installed)


@pytest.mark.parametrize("mode", [0o775, 0o757, 0o777, 0o4755, 0o2755, 0o644])
def test_helper_file_mode_fails_closed(harness: ModuleType, helper: Path, mode: int) -> None:
    helper.chmod(mode)
    with pytest.raises(RuntimeConfinementUnavailable) as failure:
        harness._require_helper_filesystem(helper)
    assert failure.value.stage is ConfinementFailureStage.HELPER_FILE_MODE
    assert str(failure.value) == "CONFINEMENT_UNAVAILABLE"
    assert failure.value.__suppress_context__


@pytest.mark.parametrize("mode", [0o775, 0o757, 0o777, 0o1777])
@pytest.mark.parametrize("ancestor", [False, True])
def test_every_parent_including_sticky_writable_parent_is_rejected(
    harness: ModuleType, helper: Path, mode: int, ancestor: bool
) -> None:
    parent = helper.parent.parent if ancestor else helper.parent
    parent.chmod(mode)
    with pytest.raises(RuntimeConfinementUnavailable) as failure:
        harness._require_helper_filesystem(helper)
    assert failure.value.stage is ConfinementFailureStage.HELPER_PARENT_TRUST


@pytest.mark.parametrize("parent_symlink", [False, True])
def test_symlink_topology_fails_closed(
    harness: ModuleType, helper: Path, parent_symlink: bool
) -> None:
    link = helper.parent.parent / "alias"
    link.symlink_to(helper.parent if parent_symlink else helper, target_is_directory=parent_symlink)
    with pytest.raises(RuntimeConfinementUnavailable) as failure:
        harness._require_helper_filesystem(link / helper.name if parent_symlink else link)
    assert failure.value.stage is (
        ConfinementFailureStage.HELPER_PARENT_TRUST
        if parent_symlink
        else ConfinementFailureStage.HELPER_FILE_MODE
    )


def test_harness_entrypoint_emits_bounded_mode_failure_before_initialization(
    harness: ModuleType,
    helper: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    helper.chmod(0o777)
    runtime = helper.parent.parent / "not-created"
    args = argparse.Namespace(node_runtime_directory=runtime, trusted_helper=helper)
    monkeypatch.setattr(harness, "arguments", lambda: args)

    def forbidden_node(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("invalid helper must not initialize Node or execute probes")

    monkeypatch.setattr(harness, "ExecutionNode", forbidden_node)
    assert harness.main() == 1
    assert not runtime.exists()
    output = capsys.readouterr()
    assert not output.err and "sensitive-path-canary" not in output.out
    assert json.loads(output.out) == {
        "profile": "m20-e5-linux-bwrap-cgroup@1",
        "result": "FAIL",
        "reason": "CONFINEMENT_UNAVAILABLE",
        "probe": None,
        "stage": "helper_file_mode",
        "runtime": "UNAVAILABLE",
        "ready": False,
    }


def test_parent_failure_diagnostic_is_bounded(harness: ModuleType, helper: Path) -> None:
    helper.parent.chmod(0o777)
    with pytest.raises(RuntimeConfinementUnavailable) as failure:
        harness._require_helper_filesystem(helper)
    encoded = harness._failure_json(failure.value)
    assert "sensitive-path-canary" not in encoded
    assert json.loads(encoded)["stage"] == "helper_parent_trust"
