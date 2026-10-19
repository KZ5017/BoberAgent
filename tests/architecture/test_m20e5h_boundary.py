"""Manual H composition cannot become another provider, executor or E6 finalizer."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/manual-smoke"


def test_h_uses_existing_production_composition_without_runtime_shortcuts() -> None:
    main = (SCRIPTS / "m20e5h_acceptance_smoke_test.py").read_text()
    local = (SCRIPTS / "_m20e5h_node.py").read_text()
    assert "CorePythonRuntimeService" in main and "CapabilityRouter" in main
    assert "McpTransport" in main and "synchronize_artifacts" in main
    assert "type(backend) is LinuxRuntimeConfinementBackend" in local
    assert "PRAGMA query_only=ON" in local
    for path in SCRIPTS.glob("*m20e5h*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not {item.name for item in node.names} & {
                    "FakeEnvironmentBackend",
                    "GenerationBackend",
                    "ControlledConfinement",
                    "ExecutionAuthorization",
                    "CapabilityResult",
                    "RuntimePreparationManifest",
                }
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                assert name not in {
                    "execute_plan",
                    "run_tool",
                    "create_empty_environment",
                    "reserve_budget",
                    "claim",
                    "settle_budget",
                    "persist_terminal",
                    "materialize_zip",
                    "extractall",
                    "chmod",
                    "fchmod",
                    "compile",
                    "eval",
                    "exec",
                    "create_session",
                    "create_resource",
                    "resolve_secret",
                    "NodePreparationService",  # constructor performs startup recovery
                }
    assert not list((ROOT / "scripts").glob("*e5h*provision*"))
