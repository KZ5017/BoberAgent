"""E5-E closed trusted construction cannot promote READY or execute source."""

import ast
import inspect
from pathlib import Path

from boberagent_execution_node.preparation.python_environment import PythonEnvironmentProvider
from boberagent_execution_node.preparation.runtime_confinement import LinuxRuntimeConfinementBackend
from boberagent_execution_node.preparation.runtime_confinement_models import (
    EnvironmentLimits,
    ProbeLimits,
)

ROOT = Path(__file__).resolve().parents[2]
PREPARATION = ROOT / "packages/execution-node/src/boberagent_execution_node/preparation"


def test_only_typed_claim_and_cancellation_request_surface() -> None:
    assert set(
        inspect.signature(PythonEnvironmentProvider.create_empty_environment).parameters
    ) == {"self", "claim", "cancellation"}
    for name in (
        "python_environment.py",
        "environment_storage.py",
        "environment_models.py",
        "_environment_helper.py",
    ):
        tree = ast.parse((PREPARATION / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {a.name.split(".")[0] for a in node.names} & {
                    "pip",
                    "ensurepip",
                    "subprocess",
                    "socket",
                    "httpx",
                    "boberagent_core",
                    "boberagent_transport_mcp",
                }
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in {
                    "boberagent_core",
                    "boberagent_transport",
                    "boberagent_transport_mcp",
                }
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
                assert (
                    node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                ) not in {
                    "run_tool",
                    "execute_plan",
                    "dispatch",
                    "eval",
                    "exec",
                    "compile",
                    "extractall",
                    "resolve_secret",
                    "create_subprocess_exec",
                }
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"READY", "VALID", "PUBLISHED"}


def test_fixed_limits_do_not_enlarge_closed_c_d_probes() -> None:
    assert ProbeLimits().scratch_bytes == 1024**2
    assert ProbeLimits().memory_bytes == 64 * 1024**2
    assert ProbeLimits().seconds == 3
    assert EnvironmentLimits().scratch_bytes == 32 * 1024**2
    assert EnvironmentLimits().memory_bytes == 128 * 1024**2
    assert EnvironmentLimits().seconds == 30
    native = (PREPARATION / "native/e5_confinement.c").read_text()
    assert '"size=33554432,nr_inodes=256,mode=0700"' in native
    assert '"-I","-S","-B","/trusted/environment.py","create"' in native
    assert '"-I","-B","/trusted/environment.py","verify"' in native
    assert "export_environment(exported,destination,deadline)" in native
    assert "kill_empty(group)" in native
    assert "NOCHILD(SYS_fork),NOCHILD(SYS_vfork),NOCHILD(SYS_clone)" in native


def test_environment_launch_uses_installed_asset_not_package_source() -> None:
    launch = inspect.getsource(LinuxRuntimeConfinementBackend._run_operation)
    assert "str(environment_helper)" in launch
    assert 'with_name("_environment_helper.py")' not in launch
    assert "self._environment_helper(environment_helper_sha256)" in launch
    assert launch.index("self._environment_helper(environment_helper_sha256)") < launch.index(
        "journal.begin("
    )
