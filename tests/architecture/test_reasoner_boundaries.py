"""The advisory Core Reasoner must not acquire an execution or secret-reveal path."""

from __future__ import annotations

import ast
from pathlib import Path

REASONER_SOURCE = (
    Path(__file__).resolve().parents[2] / "packages/core/src/boberagent_core/reasoning"
)
FORBIDDEN_IMPORTS = (
    "boberagent_execution_node",
    "boberagent_sdk",
    "boberagent_transport",
    "boberagent_transport_mcp",
    "mcp",
    "subprocess",
)
FORBIDDEN_CALLS = frozenset(
    {"dispatch", "submit_invocation", "resolve_for_run", "reveal_for_operator"}
)


def test_reasoning_modules_have_no_execution_or_secret_resolution_boundary() -> None:
    violations: list[str] = []
    for path in sorted(REASONER_SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names = (node.module,)
            else:
                names = ()
            for name in names:
                if any(
                    name == forbidden or name.startswith(f"{forbidden}.")
                    for forbidden in FORBIDDEN_IMPORTS
                ):
                    violations.append(f"{path}: import {name}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_CALLS
            ):
                violations.append(f"{path}: {node.func.attr}()")
    assert not violations, violations
