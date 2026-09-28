"""M20-C1 reads retained Core evidence without source execution or transport dependencies."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSPECTIONS = ROOT / "packages/core/src/boberagent_core/inspections"
INDEPENDENT = (
    ROOT / "packages/contracts/src",
    ROOT / "packages/sdk/src",
    ROOT / "packages/execution-node/src",
    ROOT / "packages/transport/src",
)
FORBIDDEN_IMPORTS = (
    "boberagent_execution_node",
    "boberagent_transport_mcp",
    "boberagent_capability_",
    "boberagent_core.knowledge",
    "boberagent_core.reasoning",
    "boberagent_core.llm",
    "boberagent_core.capabilities.router",
    "requests",
    "importlib",
    "runpy",
    "boberagent_core.research.providers",
    "boberagent_sdk",
    "subprocess",
    "socket",
    "httpx",
    "urllib.request",
)
FORBIDDEN_CALLS = frozenset(
    {
        "extract",
        "extractall",
        "exec",
        "eval",
        "compile",
        "run_tool",
        "execute_plan",
        "dispatch",
        "submit_invocation",
        "urlopen",
        "__import__",
        "ExecutionPlan",
        "system",
        "popen",
        "Popen",
        "run_path",
        "run_module",
    }
)


def _imports(tree: ast.AST) -> tuple[str, ...]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return tuple(names)


def test_core_inspection_is_read_only_and_offline() -> None:
    violations: list[str] = []
    for path in sorted(INSPECTIONS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _imports(tree):
            if any(name == banned or name.startswith(f"{banned}.") for banned in FORBIDDEN_IMPORTS):
                violations.append(f"{path}: import {name}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                literal_regex = (
                    name == "compile"
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "re"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                )
                if name in FORBIDDEN_CALLS and not literal_regex:
                    violations.append(f"{path}: call {name}")
    assert not violations, violations


def test_non_core_packages_do_not_import_private_inspection_domain() -> None:
    violations = [
        f"{path}: {name}"
        for directory in INDEPENDENT
        for path in sorted(directory.rglob("*.py"))
        for name in _imports(ast.parse(path.read_text(encoding="utf-8")))
        if name.startswith("boberagent_core.inspections")
    ]
    assert not violations, violations


def test_c3_consumes_history_not_source_or_execution_services() -> None:
    """C3 is a separate policy layer, not an alias for the C1/C2 reader."""
    forbidden = {
        "ast",
        "pathlib",
        "zipfile",
        "evidence",
        "service",
        "semantic_analysis",
        "extraction",
        "python_analysis",
        "lexical_analysis",
        "data_analysis",
        "text",
        "boberagent_core.artifacts",
        "boberagent_core.secrets",
        "boberagent_core.workflows",
        "boberagent_core.interactions",
    }
    violations: list[str] = []
    for filename in ("classifier.py", "classification_models.py", "classification_service.py"):
        path = INSPECTIONS / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for name in _imports(tree):
            if any(name == banned or name.startswith(banned + ".") for banned in forbidden):
                violations.append(f"{filename}: import {name}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if name in {
                    "open",
                    "open_content",
                    "read_text",
                    "read_bytes",
                    "read_citation",
                    "verify_entry",
                    "parse",
                    "analyze_semantics",
                    "VerifiedSource",
                    "resolve",
                    "allocate",
                    "create_workspace",
                }:
                    violations.append(f"{filename}: call {name}")
    assert not violations, violations
