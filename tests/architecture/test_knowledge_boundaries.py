"""Keep reusable Knowledge separate from Mission state and runtime infrastructure."""

from __future__ import annotations

import ast
from pathlib import Path

KNOWLEDGE_SOURCE = (
    Path(__file__).resolve().parents[2] / "packages/core/src/boberagent_core/knowledge"
)
FORBIDDEN = (
    "boberagent_capability_",
    "boberagent_core.artifacts",
    "boberagent_core.credentials",
    "boberagent_core.persistence",
    "boberagent_core.secrets",
    "boberagent_core.state",
    "boberagent_execution_node",
    "boberagent_sdk",
    "boberagent_transport",
    "mcp",
    "sqlalchemy",
)


def test_knowledge_layer_does_not_import_mission_or_runtime_implementations() -> None:
    violations: list[str] = []
    for path in sorted(KNOWLEDGE_SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                if module.startswith(FORBIDDEN):
                    violations.append(f"{path.name}: {module}")
    assert not violations, violations
