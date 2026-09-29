"""D3 can read authoritative metadata and persist admission, not run later phases."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANNING = ROOT / "packages/core/src/boberagent_core/planning"
ALLOWED = {
    "hashlib",
    "json",
    "classification_models",
    "evidence_models",
    "semantic_models",
    "collections.abc",
    "datetime",
    "uuid",
    "enum",
    "typing",
    "pydantic",
    "boberagent_contracts",
    "boberagent_contracts._base",
    "boberagent_contracts.plan_canonical",
    "boberagent_contracts.plan_requirements",
    "boberagent_core.acquisitions.models",
    "boberagent_core.clock",
    "boberagent_core.inspections.classification_models",
    "boberagent_core.inspections.config_identity",
    "boberagent_core.inspections.identity",
    "boberagent_core.inspections.models",
    "boberagent_core.inspections.semantic_models",
    "boberagent_core.persistence",
    "boberagent_core.persistence.repositories",
    "admission_models",
    "admission_errors",
    "models",
}
FORBIDDEN_CALLS = {
    "PlanProposal",
    "ExecutionPlan",
    "ExecutionPlanV2",
    "PlanValidation",
    "PlanPolicyAssessment",
    "OperatorPlanApproval",
    "finalize",
    "append",
    "update_proposal",
    "request",
    "dispatch",
    "submit_invocation",
    "run_tool",
    "execute_plan",
    "store",
    "resolve",
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
}


def test_d3_admission_is_metadata_only_and_stops_before_construction() -> None:
    violations: list[str] = []
    paths = (
        *(
            PLANNING / name
            for name in ("admission.py", "admission_models.py", "admission_errors.py")
        ),
        ROOT / "packages/core/src/boberagent_core/inspections/config_identity.py",
    )
    for path in paths:
        name = path.name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            imports = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else []
            )
            violations.extend(
                f"{name}: import {module}" for module in imports if module not in ALLOWED
            )
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
