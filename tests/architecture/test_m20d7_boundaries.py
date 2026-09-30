"""D7 acceptance code cannot become an execution or network adapter."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    ROOT / "packages/core/tests/m20d7_vertical_harness.py",
    ROOT / "scripts/manual-smoke/m20d7_synthetic_planning_vertical_smoke_test.py",
)
FORBIDDEN_IMPORTS = (
    "boberagent_transport",
    "boberagent_execution_node",
    "boberagent_sdk",
    "boberagent_transport_mcp",
    "boberagent_core.reasoning",
    "boberagent_core.knowledge",
    "boberagent_core.secrets",
    "subprocess",
    "socket",
    "httpx",
    "requests",
    "urllib.request",
)
FORBIDDEN_CALLS = {
    "dispatch",
    "submit_invocation",
    "run_tool",
    "execute_plan",
    "execution_grants",
    "allocate",
    "acquire",
    "install",
    "Popen",
    "system",
    "eval",
    "exec",
}


def test_d7_harness_stops_at_core_planning_boundary() -> None:
    violations: list[str] = []
    for path in FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else []
            )
            for module in modules:
                if any(
                    module == banned or module.startswith(banned + ".")
                    for banned in FORBIDDEN_IMPORTS
                ):
                    violations.append(f"{path.name}: import {module}")
            if isinstance(node, ast.Call):
                call = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if call in FORBIDDEN_CALLS:
                    violations.append(f"{path.name}: call {call}")
    assert not violations, violations
