"""M20-A research stays in Core and has no acquisition or execution path."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "packages/core/src/boberagent_core/research"
INDEPENDENT = (
    ROOT / "packages/contracts/src",
    ROOT / "packages/sdk/src",
    ROOT / "packages/execution-node/src",
)
FORBIDDEN_IMPORTS = (
    "boberagent_execution_node",
    "boberagent_sdk",
    "boberagent_transport",
    "boberagent_transport_mcp",
    "boberagent_capability_",
    "subprocess",
    "mcp",
)
FORBIDDEN_CALLS = frozenset(
    {
        "dispatch",
        "submit_invocation",
        "execute_plan",
        "run_tool",
        "create_workspace",
        "create_artifact",
        "append_observation",
    }
)


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return tuple(imports)


def test_research_package_has_no_execution_or_acquisition_dependency() -> None:
    violations: list[str] = []
    for path in sorted(RESEARCH.rglob("*.py")):
        for name in _imports(path):
            if any(name == banned or name.startswith(f"{banned}.") for banned in FORBIDDEN_IMPORTS):
                violations.append(f"{path}: import {name}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_CALLS
            ):
                violations.append(f"{path}: call {node.func.attr}")
    assert not violations, violations


def test_contract_sdk_and_node_do_not_import_core_research() -> None:
    violations = [
        str(path)
        for directory in INDEPENDENT
        for path in sorted(directory.rglob("*.py"))
        if any(name.startswith("boberagent_core.research") for name in _imports(path))
    ]
    assert not violations, violations
