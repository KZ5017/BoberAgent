"""The retained-source operator harness cannot become a fetch/execute path."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts/manual-smoke/m20c4_real_retained_source_inspection_smoke_test.py"


def test_c4_smoke_is_core_only_offline_and_never_executes_source() -> None:
    tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
    imports = [
        name
        for node in ast.walk(tree)
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else []
        )
    ]
    forbidden_imports = (
        "boberagent_execution_node",
        "boberagent_transport",
        "boberagent_sdk",
        "boberagent_capability_",
        "boberagent_core.knowledge",
        "boberagent_core.reasoning",
        "boberagent_core.secrets",
        "boberagent_core.research.providers",
        "tests",
        "subprocess",
        "socket",
        "http",
        "httpx",
        "requests",
        "urllib",
        "importlib",
        "runpy",
    )
    assert not [name for name in imports if name.startswith(forbidden_imports)]
    forbidden_calls = {
        "extract",
        "extractall",
        "eval",
        "exec",
        "compile",
        "__import__",
        "run_tool",
        "execute_plan",
        "dispatch",
        "submit_invocation",
        "ExecutionPlan",
        "system",
        "popen",
        "Popen",
        "urlopen",
        "create_acquisition",
        "build_invocation",
        "getenv",
        "operator_environment",
        "analyze_semantics",
        "classify_support",
    }
    calls = [
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute | ast.Name)
    ]
    assert not set(calls) & forbidden_calls
