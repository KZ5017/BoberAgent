"""E2 owns Core metadata-only admission, not source access or runtime work."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E2_SOURCES = (
    ROOT / "packages/core/src/boberagent_core/preparation/models.py",
    ROOT / "packages/core/src/boberagent_core/preparation/repository.py",
    ROOT / "packages/core/src/boberagent_core/preparation/service.py",
)
FORBIDDEN_IMPORTS = (
    "boberagent_execution_node",
    "boberagent_transport_mcp",
    "boberagent_sdk",
    "boberagent_capability_",
    "subprocess",
    "socket",
    "httpx",
    "requests",
    "urllib.request",
    "zipfile",
    "pip",
    "boberagent_core.artifacts.storage",
    "boberagent_core.artifacts.receiver",
    "boberagent_core.capabilities.router",
)
FORBIDDEN_CALLS = {
    "dispatch",
    "submit_invocation",
    "run_tool",
    "execute_plan",
    "create_workspace",
    "extract",
    "extractall",
    "read_bytes",
    "open",
    "resolve_secret",
}


def test_e2_has_no_transport_execution_source_or_secret_access() -> None:
    for source in E2_SOURCES:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        imports = (
            name
            for node in ast.walk(tree)
            for name in (
                ([alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            )
        )
        for name in imports:
            assert not any(
                name == banned or name.startswith(banned + ".") for banned in FORBIDDEN_IMPORTS
            )
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not calls & FORBIDDEN_CALLS, source
