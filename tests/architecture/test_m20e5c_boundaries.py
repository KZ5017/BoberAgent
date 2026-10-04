"""Closed trusted probes cannot turn into a Python/source/provider executor."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREPARATION = ROOT / "packages/execution-node/src/boberagent_execution_node/preparation"


def test_confinement_has_no_later_slice_or_execution_authority() -> None:
    forbidden = {
        "venv",
        "pip",
        "ensurepip",
        "boberagent_core",
        "boberagent_transport_mcp",
        "importlib",
        "httpx",
    }
    calls = {
        "run_tool",
        "execute_plan",
        "dispatch",
        "create_session",
        "resolve_secret",
        "compile",
        "eval",
        "exec",
        "extractall",
        "materialize_zip",
        "inspect_interpreter",
        "create_empty_environment",
    }
    for file in PREPARATION.glob("runtime_confinement*.py"):
        tree = ast.parse(file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {alias.name.split(".")[0] for alias in node.names} & forbidden
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden
                assert not {alias.name for alias in node.names} & {
                    "PythonRuntimeBinding",
                    "PythonInterpreterIdentity",
                    "ExecutionAuthorization",
                    "ExecutionPlan",
                    "ExecutionPlanV2",
                }
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
                assert (
                    node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                ) not in calls
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"READY", "VALID", "PUBLISHED", "VERIFYING"}
    native = (PREPARATION / "native/e5_confinement.c").read_text()
    for forbidden_text in (
        "/usr/bin/python",
        "system(",
        "popen(",
        "--ro-bind / /",
        "sudo",
        "pip install",
    ):
        assert forbidden_text not in native
    assert "SYS_close_range" in native
    assert "PR_SET_PDEATHSIG" in native
    assert "cgroup.kill" in native
    assert "nr_inodes=32" in native
    assert "SECCOMP_RET_ERRNO|EPERM" in native
