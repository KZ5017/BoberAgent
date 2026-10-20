"""E6 completion cannot acquire execution or platform implementation authority."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NODE = ROOT / "packages/execution-node/src/boberagent_execution_node"
CORE = ROOT / "packages/core/src/boberagent_core"


def test_preparation_capability_uses_only_contract_and_sdk_port() -> None:
    tree = ast.parse((NODE / "preparation/capability.py").read_text())
    imports = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert imports <= {"typing", "pydantic", "boberagent_contracts", "boberagent_sdk"}
    calls = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "prepare_runtime" in calls
    assert not calls & {"execute_plan", "run_tool", "resolve", "dispatch", "create_subprocess_exec"}


def test_completion_adapters_cannot_construct_or_execute_runtime_or_source() -> None:
    forbidden = {
        "exec",
        "eval",
        "compile",
        "run_tool",
        "execute_plan",
        "create_subprocess_exec",
        "create_subprocess_shell",
        "construct",
        "create_empty_environment",
        "revalidate_environment",
        "materialize_zip",
        "install",
        "acquire",
        "create_session",
        "execution_grants",
    }
    for path in (CORE / "preparation/completion.py", NODE / "preparation/completion.py"):
        tree = ast.parse(path.read_text())
        calls = {
            n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, (ast.Attribute, ast.Name))
        }
        assert not calls & forbidden, path
        imports = {
            n.module.split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module
        }
        assert not imports & {"subprocess", "socket", "venv", "pip", "boberagent_transport_mcp"}
    production_process = ast.parse((NODE / "processes/service.py").read_text())
    execute = next(
        n
        for n in ast.walk(production_process)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "execute_plan"
    )
    assert any(
        isinstance(n, ast.Raise)
        and isinstance(n.exc, ast.Call)
        and isinstance(n.exc.func, ast.Name)
        and n.exc.func.id == "PolicyDenied"
        for n in ast.walk(execute)
    )
    assert not any(isinstance(n, ast.Await) for n in ast.walk(execute))
