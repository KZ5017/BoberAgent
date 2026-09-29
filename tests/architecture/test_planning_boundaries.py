"""D1 is domain/schema only; no execution, persistence, analysis or HITL machinery."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANNING = ROOT / "packages/core/src/boberagent_core/planning"
CONTRACTS = ROOT / "packages/contracts/src/boberagent_contracts"
FORBIDDEN_IMPORTS = (
    "boberagent_sdk",
    "boberagent_execution_node",
    "boberagent_transport",
    "boberagent_transport_mcp",
    "boberagent_capability_",
    "boberagent_core.capabilities",
    "boberagent_core.persistence",
    "boberagent_core.artifacts",
    "boberagent_core.secrets",
    "boberagent_core.interactions",
    "boberagent_core.knowledge",
    "boberagent_core.reasoning",
    "boberagent_core.llm",
    "boberagent_core.inspections.service",
    "boberagent_core.inspections.classifier",
    "boberagent_core.inspections.classification_service",
    "boberagent_core.inspections.extraction",
    "boberagent_core.inspections.semantic_analysis",
    "boberagent_core.inspections.evidence",
    "subprocess",
    "socket",
    "httpx",
    "requests",
    "urllib.request",
    "sqlalchemy",
    "alembic",
    "zipfile",
    "importlib",
    "runpy",
    "pathlib",
    "os",
    "shutil",
    "boberagent_core.research.providers",
)
ALLOWED_IMPORTS = {
    "enum",
    "typing",
    "pydantic",
    "ipaddress",
    "urllib.parse",
    "hashlib",
    "json",
    "datetime",
    "_base",
    "artifact",
    "enums",
    "refs",
    "poc_acquisition",
    "execution_plan",
    "plan_canonical",
    "plan_requirements",
    "plan_values",
    "models",
    "fingerprints",
    "records",
    "admission_models",
    "boberagent_contracts",
    "boberagent_contracts._base",
    "boberagent_contracts.execution_plan_v2",
    "boberagent_contracts.plan_canonical",
    "boberagent_contracts.plan_requirements",
    "boberagent_contracts.plan_values",
    "boberagent_core.inspections.classification_models",
    "boberagent_core.inspections.identity",
    "boberagent_core.research.models",
}
FORBIDDEN_CALLS = {
    "dispatch",
    "submit_invocation",
    "run_tool",
    "execute_plan",
    "resolve",
    "store",
    "allocate",
    "acquire",
    "create_workspace",
    "extract",
    "extractall",
    "open",
    "read_bytes",
    "read_text",
    "write_bytes",
    "write_text",
    "exec",
    "eval",
    "__import__",
    "system",
    "popen",
    "Popen",
    "analyze_semantics",
    "classify",
    "request",
    "save",
    "commit",
    "connect",
    "urlopen",
}


def test_d1_modules_have_no_side_effect_dependencies() -> None:
    violations: list[str] = []
    paths = (
        *(
            PLANNING / name
            for name in (
                "__init__.py",
                "models.py",
                "fingerprints.py",
                "records.py",
                "admission_models.py",
            )
        ),
        *(
            CONTRACTS / name
            for name in (
                "execution_plan_v2.py",
                "plan_values.py",
                "plan_requirements.py",
                "plan_canonical.py",
            )
        ),
    )
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            )
            for name in names:
                if name not in ALLOWED_IMPORTS:
                    violations.append(f"{path.name}: non-domain import {name}")
                if any(
                    name == banned
                    or name.startswith(banned + ".")
                    or (banned.endswith("_") and name.startswith(banned))
                    for banned in FORBIDDEN_IMPORTS
                ):
                    violations.append(f"{path.name}: import {name}")
            if isinstance(node, ast.Call):
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else (node.func.id if isinstance(node.func, ast.Name) else "")
                )
                if name in FORBIDDEN_CALLS:
                    violations.append(f"{path.name}: call {name}")
    assert not violations, violations


def test_planning_namespace_has_only_domain_persistence_and_admission() -> None:
    assert {path.name for path in PLANNING.glob("*.py")} == {
        "__init__.py",
        "models.py",
        "fingerprints.py",
        "records.py",
        "errors.py",
        "repository.py",
        "admission.py",
        "admission_models.py",
        "admission_errors.py",
    }
