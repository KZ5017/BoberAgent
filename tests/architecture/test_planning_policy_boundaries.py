"""D5 may assess persisted intent, but cannot approve, contact or execute it."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANNING = ROOT / "packages/core/src/boberagent_core/planning"
FORBIDDEN_IMPORT_FRAGMENTS = (
    "transport",
    "execution_node",
    "sdk",
    "capability_",
    "subprocess",
    "socket",
    "httpx",
    "requests",
    "sqlalchemy",
    "alembic",
    "secrets",
    "interactions",
    "reasoning",
    "knowledge",
    "inspection.service",
    "inspection.classifier",
    "inspections.semantic_analysis",
)
FORBIDDEN_CALLS = {
    "dispatch",
    "submit_invocation",
    "run_tool",
    "execute_plan",
    "store",
    "execution_grants",
    "acquire",
    "allocate",
    "resolve",
    "install",
    "extract",
    "open",
    "read_bytes",
    "read_text",
    "Popen",
    "system",
    "OperatorPlanApproval",
    "InteractionRequest",
    "CapabilityRun",
}


def test_d5_has_no_runtime_or_human_approval_dependencies() -> None:
    violations: list[str] = []
    for name in ("policy_models.py", "policy_evaluator.py", "policy_service.py"):
        tree = ast.parse((PLANNING / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else []
            )
            for module in modules:
                if any(fragment in module for fragment in FORBIDDEN_IMPORT_FRAGMENTS):
                    violations.append(f"{name}: import {module}")
            if isinstance(node, ast.Call):
                call = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if call in FORBIDDEN_CALLS:
                    violations.append(f"{name}: call {call}")
    assert not violations, violations


def test_d5_evaluator_is_pure() -> None:
    tree = ast.parse((PLANNING / "policy_evaluator.py").read_text(encoding="utf-8"))
    imports = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    ]
    assert not any("persistence" in module or "policy_service" in module for module in imports)
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"unit_of_work", "commit", "get", "finalize"}
        for node in ast.walk(tree)
    )
