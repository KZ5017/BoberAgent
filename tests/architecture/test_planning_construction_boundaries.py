"""D4 can construct/validate intent; policy and execution are separate phases."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANNING = ROOT / "packages/core/src/boberagent_core/planning"
ALLOWED = {
    "collections.abc",
    "datetime",
    "uuid",
    "typing",
    "pydantic",
    "boberagent_contracts",
    "boberagent_contracts._base",
    "boberagent_contracts.plan_values",
    "boberagent_contracts.plan_requirements",
    "boberagent_contracts.plan_canonical",
    "boberagent_core.clock",
    "boberagent_core.models",
    "boberagent_core.inspections.semantic_models",
    "boberagent_core.inspections.classification_models",
    "boberagent_core.persistence",
    "boberagent_core.persistence.repositories",
    "admission",
    "admission_models",
    "models",
    "construction_models",
    "errors",
    "records",
    "validation",
}
FORBIDDEN_CALLS = {
    "dispatch",
    "submit_invocation",
    "run_tool",
    "execute_plan",
    "resolve",
    "store",
    "execution_grants",
    "acquire",
    "allocate",
    "inspect",
    "classify",
    "analyze_semantics",
    "read_citation",
    "open_content",
    "open",
    "read_bytes",
    "read_text",
    "write_bytes",
    "write_text",
    "extract",
    "extractall",
    "exec",
    "eval",
    "install",
    "urlopen",
    "Popen",
    "system",
    "commit",
    "request",
    "PlanPolicyAssessment",
    "OperatorPlanApproval",
    "CapabilityRun",
}


def test_d4_has_no_source_policy_or_execution_dependencies() -> None:
    violations: list[str] = []
    for name in ("construction.py", "construction_models.py", "validation.py"):
        for node in ast.walk(ast.parse((PLANNING / name).read_text(encoding="utf-8"))):
            imports = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            )
            violations.extend(
                f"{name}: import {module}" for module in imports if module not in ALLOWED
            )
            if isinstance(node, ast.Call):
                call = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else (node.func.id if isinstance(node.func, ast.Name) else "")
                )
                if call in FORBIDDEN_CALLS:
                    violations.append(f"{name}: call {call}")
    assert not violations, violations


def test_d4_validator_is_pure() -> None:
    tree = ast.parse((PLANNING / "validation.py").read_text(encoding="utf-8"))
    imports = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    ]
    assert not any(
        "persistence" in module or module in {"construction", "admission"} for module in imports
    )
    forbidden = {"finalize", "append", "update_proposal", "update_lifecycle", "unit_of_work"}
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in forbidden
        for node in ast.walk(tree)
    )
