"""E1 must remain a pure Contract/SDK boundary, not an early preparation runtime."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E1_SOURCES = (
    ROOT / "packages/contracts/src/boberagent_contracts/runtime_preparation.py",
    ROOT / "packages/sdk/src/boberagent_sdk/services/preparation.py",
    ROOT / "packages/sdk/src/boberagent_sdk/testing/preparation.py",
)
FORBIDDEN_IMPORTS = frozenset(
    {
        "boberagent_core",
        "boberagent_execution_node",
        "boberagent_transport",
        "boberagent_transport_mcp",
        "mcp",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "pip",
        "sqlalchemy",
        "alembic",
        "boberagent_reasoning",
    }
)


def test_e1_modules_have_no_runtime_or_infrastructure_imports() -> None:
    for source in E1_SOURCES:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imports = {
            name.split(".")[0]
            for node in ast.walk(tree)
            for name in (
                ([alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            )
        }
        assert not imports & FORBIDDEN_IMPORTS, source
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not calls & {"run_tool", "execute_plan", "create_subprocess_exec", "system"}, source


def test_production_execute_plan_still_denies() -> None:
    source = ROOT / "packages/execution-node/src/boberagent_execution_node/processes/service.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute_plan"
    )
    assert any(
        isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id == "PolicyDenied"
        for node in ast.walk(method)
    )
