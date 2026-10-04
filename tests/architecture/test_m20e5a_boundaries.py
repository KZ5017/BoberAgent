"""E5-A is an unwired data boundary. Provider/persistence/runtime work remains later."""

import ast
from pathlib import Path

from boberagent_contracts import PythonResourceState
from boberagent_execution_node.persistence import ResourceRuntimeState

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "packages/contracts/src/boberagent_contracts/python_runtime.py"
TRANSPORT = ROOT / "packages/transport/src/boberagent_transport/preparation_runtime.py"


def test_data_boundary_has_no_execution_or_infrastructure_dependencies() -> None:
    forbidden_imports = {
        "boberagent_core",
        "boberagent_execution_node",
        "boberagent_sdk",
        "boberagent_transport_mcp",
        "sqlalchemy",
        "alembic",
        "venv",
        "pip",
        "ensurepip",
        "subprocess",
        "socket",
        "httpx",
        "os",
        "pathlib",
        "boberagent_reasoning",
        "importlib",
        "asyncio",
    }
    forbidden_calls = {
        "run_tool",
        "execute_plan",
        "create_subprocess_exec",
        "system",
        "open",
        "exec",
        "eval",
        "compile",
        "extract",
        "extractall",
        "resolve",
        "mkdir",
        "create_session",
        "create_resource",
        "dispatch",
        "materialize",
    }
    for source in (CONTRACT, TRANSPORT):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imports = {
            name.split(".")[0]
            for node in ast.walk(tree)
            for name in (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else []
            )
        }
        assert not imports & forbidden_imports
        calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
        }
        assert not calls & forbidden_calls
        assert not any(isinstance(node, ast.AsyncFunctionDef) for node in ast.walk(tree))


def test_new_shared_state_matches_existing_node_vocabulary() -> None:
    assert {state.value for state in PythonResourceState} == {
        state.value for state in ResourceRuntimeState
    }


def test_new_protocol_is_not_wired_to_runtime_or_adapters() -> None:
    for package in ("core", "execution-node", "transport-mcp"):
        for source in (ROOT / "packages" / package / "src").rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.endswith("preparation_runtime"), source
                    assert not any(
                        alias.name.startswith("PythonRuntime") for alias in node.names
                    ), source


def test_production_generic_resource_has_no_python_provider() -> None:
    source = (
        ROOT / "packages/execution-node/src/boberagent_execution_node/services/resource_sessions.py"
    )
    text = source.read_text(encoding="utf-8")
    assert "unsupported Resource type" in text
    assert "python_runtime" not in text
