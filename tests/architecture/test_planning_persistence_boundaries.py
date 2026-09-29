"""D2 may persist planning truth, but cannot perform D3-D6/E/F behavior."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATHS = (
    ROOT / "packages/core/src/boberagent_core/planning/repository.py",
    ROOT / "packages/core/src/boberagent_core/planning/errors.py",
    ROOT / "packages/core/src/boberagent_core/persistence/planning_orm.py",
    ROOT
    / "packages/core/src/boberagent_core/persistence/migrations/versions/0013_m20_d2_planning.py",
)
ALLOWED = {
    "collections.abc",
    "contextlib",
    "datetime",
    "sqlite3",
    "typing",
    "pydantic",
    "boberagent_contracts",
    "boberagent_contracts.plan_canonical",
    "boberagent_contracts.execution_plan_v2",
    "sqlalchemy",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.exc",
    "sqlalchemy.orm",
    "alembic",
    "boberagent_core.persistence.planning_orm",
    "boberagent_core.persistence.repositories",
    "errors",
    "fingerprints",
    "models",
    "records",
    "orm",
    "types",
}
FORBIDDEN_CALLS = {
    "dispatch",
    "submit_invocation",
    "execute_plan",
    "run_tool",
    "resolve",
    "store",
    "acquire",
    "allocate",
    "classify",
    "analyze_semantics",
    "extract",
    "extractall",
    "request",
    "open",
    "read_bytes",
    "read_text",
    "write_bytes",
    "write_text",
    "exec",
    "eval",
    "commit",
    "urlopen",
    "Popen",
    "system",
    "install",
}


def test_d2_persistence_has_no_evaluation_or_execution_dependencies() -> None:
    violations: list[str] = []
    for path in PATHS:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [item.name for item in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else []
            )
            for name in names:
                if name not in ALLOWED:
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
