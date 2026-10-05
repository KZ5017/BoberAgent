"""Provenance stays a closed Node-owned inspect operation, never E5-E/F."""

import ast
import inspect
from pathlib import Path

from boberagent_execution_node.preparation.runtime_confinement import LinuxRuntimeConfinementBackend
from boberagent_execution_node.preparation.runtime_confinement_models import (
    ClosedProbe,
    TrustedPythonOperation,
)

ROOT = Path(__file__).resolve().parents[2]
PREPARATION = ROOT / "packages/execution-node/src/boberagent_execution_node/preparation"


def test_no_installer_source_execution_or_readiness_api() -> None:
    forbidden = {
        "venv",
        "pip",
        "ensurepip",
        "subprocess",
        "httpx",
        "socket",
        "boberagent_core",
        "boberagent_transport_mcp",
        "importlib",
        "uv",
    }
    calls = {
        "execute_plan",
        "run_tool",
        "create_subprocess_exec",
        "dispatch",
        "resolve_secret",
        "extractall",
        "materialize_zip",
        "create_empty_environment",
        "system",
        "eval",
        "exec",
        "compile",
    }
    for name in ("python_distribution.py", "python_provenance.py", "python_projection.py"):
        tree = ast.parse((PREPARATION / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {a.name.split(".")[0] for a in node.names} & forbidden
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
                assert (
                    node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                ) not in calls
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"READY", "VALID", "PUBLISHED", "VERIFYING"}
    assert len(ClosedProbe) == 13 and list(TrustedPythonOperation) == [
        TrustedPythonOperation.IDENTITY
    ]


def test_fixed_native_program_environment_and_no_generic_execution_parameters() -> None:
    signature = inspect.signature(LinuxRuntimeConfinementBackend.run_identity)
    assert set(signature.parameters) == {"self", "distribution", "operation_id", "cancellation"}
    native = (PREPARATION / "native/e5_confinement.c").read_text()
    assert '"-I","-S","-B","-c",program' in native
    assert '"LD_LIBRARY_PATH=/runtime/lib:/support"' in native
    assert "static char program[]=" in native
    assert "execve(loader,args,env)" in native
    assert "SECCOMP_RET_ERRNO|EPERM" in native
    assert 'strcmp(argv[9],"m20-e5-python-distribution@2")' in native
    assert 'ARG("/runtime/lib")' not in native
    assert "projection_records(argv[10],source)" in native
    assert "F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL" in native
    assert (
        "write_mount_descriptor(descriptor, manifest)"
        in (PREPARATION / "runtime_confinement.py").read_text()
    )
    assert "DENY(SYS_execveat)" in native
    backend = (PREPARATION / "runtime_confinement.py").read_text()
    identity_method = inspect.getsource(LinuxRuntimeConfinementBackend.run_identity)
    assert identity_method.index("before = inventory(distribution)") < identity_method.index(
        "self._run_operation"
    )
    assert "return previous  # historical evidence only" in backend
