"""E4 source preparation cannot turn into a source execution/runtime provider."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NODE_PREPARATION = ROOT / "packages/execution-node/src/boberagent_execution_node/preparation"
SOURCES = (
    NODE_PREPARATION / "materializer.py",
    NODE_PREPARATION / "confinement.py",
    NODE_PREPARATION / "service.py",
    ROOT / "packages/core/src/boberagent_core/preparation/dispatch.py",
)
FORBIDDEN_IMPORTS = (
    "boberagent_capability_",
    "boberagent_core.inspections",
    "boberagent_core.reasoning",
    "boberagent_transport_mcp",
    "pip",
    "venv",
    "importlib",
)
FORBIDDEN_CALLS = {
    "execute_plan",
    "run_tool",
    "create_resource",
    "create_session",
    "resolve_secret",
    "extract",
    "extractall",
    "eval",
    "exec",
    "compile",
}


def test_e4_has_no_acquired_source_execution_or_cross_owner_imports() -> None:
    for source in SOURCES:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ] + [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        ]
        assert not any(
            name == banned or name.startswith(banned + ".")
            for name in imports
            for banned in FORBIDDEN_IMPORTS
        ), source
        calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        assert not calls & FORBIDDEN_CALLS, source
        if source.name != "confinement.py":
            assert "subprocess" not in imports, source
