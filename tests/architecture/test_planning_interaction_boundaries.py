"""D6 Core planning questions and approvals cannot become an execution path."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANNING = ROOT / "packages/core/src/boberagent_core/planning"
MODULES = (
    "interaction_models.py",
    "assistance_questions.py",
    "assistance.py",
    "approval.py",
)
FORBIDDEN_IMPORTS = (
    "boberagent_transport",
    "boberagent_execution_node",
    "boberagent_sdk",
    "boberagent_capability_",
    "boberagent_core.reasoning",
    "boberagent_core.knowledge",
    "boberagent_core.secrets",
    "subprocess",
    "socket",
    "httpx",
    "requests",
    "urllib.request",
    "alembic",
)
FORBIDDEN_CALLS = {
    "dispatch",
    "submit_invocation",
    "run_tool",
    "execute_plan",
    "execution_grants",
    "resolve",
    "allocate",
    "acquire",
    "install",
    "extract",
    "Popen",
    "system",
    "eval",
    "exec",
}


def test_d6_planning_hitl_is_core_local_nonexecuting() -> None:
    violations: list[str] = []
    for name in MODULES:
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
                if any(
                    module == banned or module.startswith(banned + ".")
                    for banned in FORBIDDEN_IMPORTS
                ):
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
