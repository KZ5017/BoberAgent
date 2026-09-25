"""Qdrant and embedding HTTP details stay behind their Core Knowledge adapters."""

from __future__ import annotations

import ast
from pathlib import Path

CORE_SOURCE = Path(__file__).resolve().parents[2] / "packages/core/src/boberagent_core"


def test_qdrant_and_embedding_http_dependencies_are_adapter_local() -> None:
    violations: list[str] = []
    allowed = {
        "qdrant_client": "qdrant_local.py",
        "httpx": "openai_embeddings.py",
    }
    for path in sorted(CORE_SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names = (node.module,)
            else:
                continue
            for name in names:
                for dependency, adapter in allowed.items():
                    if (name == dependency or name.startswith(f"{dependency}.")) and (
                        path.name != adapter or path.parent.name != "knowledge"
                    ):
                        violations.append(f"{path}: {name}")
    assert not violations, violations
