"""D8 manual admission must not import later planning, source or runtime authority."""

import ast
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts/manual-smoke/m20d8_real_retained_negative_planning_smoke_test.py"
)
FORBIDDEN_IMPORTS = (
    "boberagent_execution_node",
    "boberagent_transport",
    "boberagent_transport_mcp",
    "boberagent_core.planning.construction",
    "boberagent_core.planning.policy_service",
    "boberagent_core.planning.assistance",
    "boberagent_core.planning.approval",
    "boberagent_core.inspections.service",
    "boberagent_core.inspections.semantic_extractor",
    "boberagent_core.inspections.classifier",
    "boberagent_core.artifacts",
    "boberagent_core.secrets",
    "boberagent_core.reasoner",
    "boberagent_core.knowledge",
    "subprocess",
    "urllib",
    "httpx",
    "requests",
)
FORBIDDEN_CALLS = {
    "construct",
    "evaluate",
    "request",
    "answer",
    "dispatch",
    "submit_invocation",
    "open_content",
    "read_citation",
    "inspect",
    "classify",
    "open",
    "read_bytes",
    "read_text",
    "extract",
    "extractall",
    "run_tool",
    "execute_plan",
    "execution_grants",
    "acquire",
    "allocate",
    "urlopen",
    "Popen",
    "system",
    "install",
    "upgrade_database",
}


def test_d8_is_metadata_only_and_calls_only_admission() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        imports = (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else []
        )
        violations.extend(
            f"forbidden import {module}"
            for module in imports
            if any(module.startswith(prefix) for prefix in FORBIDDEN_IMPORTS)
        )
        if isinstance(node, ast.Call):
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else ""
            )
            if name in FORBIDDEN_CALLS:
                violations.append(f"forbidden call {name}")
    assert not violations, violations
