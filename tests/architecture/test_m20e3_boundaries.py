"""E3 may admit and copy opaque inputs, never prepare or execute source."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    ROOT / "packages/core/src/boberagent_core/preparation/dispatch.py",
    ROOT / "packages/execution-node/src/boberagent_execution_node/preparation/service.py",
)
FORBIDDEN_IMPORTS = (
    "boberagent_transport_mcp",
    "boberagent_capability_",
    "boberagent_core.inspections",
    "boberagent_core.reasoning",
    "zipfile",
    "subprocess",
    "socket",
    "pip",
)
FORBIDDEN_CALLS = {
    "execute_plan",
    "run_tool",
    "create_workspace",
    "extract",
    "extractall",
    "create_resource",
    "create_session",
    "resolve_secret",
    "import_module",
}


def test_e3_is_opaque_import_only() -> None:
    for source in SOURCES:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imports = (
            alias.name
            for node in ast.walk(tree)
            for alias in (node.names if isinstance(node, ast.Import) else ())
        )
        from_imports = (
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        for name in (*imports, *from_imports):
            assert not any(
                name == banned or name.startswith(banned + ".") for banned in FORBIDDEN_IMPORTS
            )
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not calls & FORBIDDEN_CALLS, source
