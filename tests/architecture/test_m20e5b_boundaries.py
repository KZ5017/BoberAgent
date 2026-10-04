"""Bookkeeping cannot construct a runtime, seal evidence or grant authority."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OWNERSHIP = ROOT / "packages/execution-node/src/boberagent_execution_node/preparation"


def test_ownership_has_no_runtime_filesystem_network_or_execution_calls() -> None:
    forbidden_imports = {
        "os",
        "pathlib",
        "subprocess",
        "asyncio",
        "socket",
        "httpx",
        "venv",
        "boberagent_core",
        "boberagent_transport_mcp",
        "boberagent_reasoning",
    }
    forbidden_calls = {
        "open",
        "mkdir",
        "read_bytes",
        "write_bytes",
        "rmtree",
        "unlink",
        "create_subprocess_exec",
        "run_tool",
        "execute_plan",
        "dispatch",
        "materialize",
        "preflight",
        "exec",
        "eval",
        "compile",
    }
    for file in (OWNERSHIP / "resources.py", OWNERSHIP / "resource_models.py"):
        tree = ast.parse(file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {alias.name.split(".")[0] for alias in node.names} & forbidden_imports
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports
                assert not node.module.endswith("preparation_runtime")
                assert not {alias.name for alias in node.names} & {
                    "PythonRuntimeEvidence",
                    "PythonRuntimeBinding",
                    "ExecutionAuthorization",
                }
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                assert name not in forbidden_calls
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"READY", "PUBLISHED", "VALID", "VERIFYING"}


def test_ownership_is_not_exposed_as_transport_or_capability_execution() -> None:
    for package in ("core", "sdk", "transport", "transport-mcp"):
        for file in (ROOT / "packages" / package / "src").rglob("*.py"):
            tree = ast.parse(file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert not any(alias.name == "PythonResourceRepository" for alias in node.names)
    source = (
        ROOT / "packages/execution-node/src/boberagent_execution_node/processes/service.py"
    ).read_text()
    assert "ExecutionPlan execution is not implemented" in source or "PolicyDenied" in source
