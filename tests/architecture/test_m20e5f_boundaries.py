"""Fresh validation is not execution or terminal E6 preparation completion."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_revalidation_and_pump_have_no_source_executor_or_terminal_result() -> None:
    files = (
        "packages/core/src/boberagent_core/preparation/runtime.py",
        "packages/execution-node/src/boberagent_execution_node/preparation/python_revalidation.py",
        "packages/execution-node/src/boberagent_execution_node/preparation/runtime_service.py",
    )
    forbidden = {
        "execute_plan",
        "run_tool",
        "create_subprocess_exec",
        "exec",
        "eval",
        "compile",
        "extractall",
        "resolve_secret",
        "persist_terminal",
    }
    for file in files:
        tree = ast.parse((ROOT / file).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in {
                    "boberagent_transport_mcp",
                    "pip",
                    "ensurepip",
                    "subprocess",
                    "socket",
                    "httpx",
                }
                assert not {a.name for a in node.names} & {
                    "CapabilityResult",
                    "ExecutionAuthorization",
                    "RuntimePreparationManifest",
                }
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
                assert (
                    node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                ) not in forbidden
