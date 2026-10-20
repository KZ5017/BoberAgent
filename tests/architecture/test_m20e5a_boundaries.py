"""E5 data stays infrastructure-free; production wiring is restricted to reviewed F adapters."""

import ast
from pathlib import Path

from boberagent_contracts import PythonResourceState
from boberagent_execution_node.persistence import ResourceRuntimeState

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "packages/contracts/src/boberagent_contracts/python_runtime.py"
TRANSPORT = ROOT / "packages/transport/src/boberagent_transport/preparation_runtime.py"


def test_data_boundary_has_no_execution_or_infrastructure_dependencies() -> None:
    forbidden_imports = {
        "boberagent_core",
        "boberagent_execution_node",
        "boberagent_sdk",
        "boberagent_transport_mcp",
        "sqlalchemy",
        "alembic",
        "venv",
        "pip",
        "ensurepip",
        "subprocess",
        "socket",
        "httpx",
        "os",
        "pathlib",
        "boberagent_reasoning",
        "importlib",
        "asyncio",
    }
    forbidden_calls = {
        "run_tool",
        "execute_plan",
        "create_subprocess_exec",
        "system",
        "open",
        "exec",
        "eval",
        "compile",
        "extract",
        "extractall",
        "resolve",
        "mkdir",
        "create_session",
        "create_resource",
        "dispatch",
        "materialize",
    }
    for source in (CONTRACT, TRANSPORT):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imports = {
            name.split(".")[0]
            for node in ast.walk(tree)
            for name in (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.module
                else []
            )
        }
        assert not imports & forbidden_imports
        calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
        }
        assert not calls & forbidden_calls
        assert not any(isinstance(node, ast.AsyncFunctionDef) for node in ast.walk(tree))


def test_new_shared_state_matches_existing_node_vocabulary() -> None:
    assert {state.value for state in PythonResourceState} == {
        state.value for state in ResourceRuntimeState
    }


def test_runtime_wiring_is_confined_to_reviewed_e5f_modules() -> None:
    ownership = ROOT / "packages/execution-node/src/boberagent_execution_node/preparation"
    wiring = {
        ownership / "runtime_service.py",
        ROOT / "packages/core/src/boberagent_core/preparation/runtime.py",
        ROOT / "packages/core/src/boberagent_core/preparation/models.py",
        ROOT / "packages/core/src/boberagent_core/preparation/completion.py",
        ownership / "completion.py",
        ROOT / "packages/execution-node/src/boberagent_execution_node/transport/endpoint.py",
        ROOT / "packages/transport-mcp/src/boberagent_transport_mcp/client.py",
    }
    for package in ("core", "execution-node", "transport-mcp"):
        for source in (ROOT / "packages" / package / "src").rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.endswith("preparation_runtime"):
                        assert source in wiring, source
                    if (
                        source
                        not in {
                            ownership / "resources.py",
                            ownership / "resource_models.py",
                            ownership / "runtime_confinement.py",
                            ownership / "runtime_confinement_budget.py",
                            ownership / "python_distribution.py",
                            ownership / "python_provenance.py",
                            ownership / "python_environment.py",
                            ownership / "environment_storage.py",
                            ownership / "environment_models.py",
                            ownership / "python_revalidation.py",
                            ownership / "service.py",
                        }
                        | wiring
                    ):
                        assert not any(
                            alias.name.startswith("PythonRuntime") for alias in node.names
                        ), source


def test_production_generic_resource_has_no_python_provider() -> None:
    source = (
        ROOT / "packages/execution-node/src/boberagent_execution_node/services/resource_sessions.py"
    )
    text = source.read_text(encoding="utf-8")
    assert "unsupported Resource type" in text
    assert "python_runtime" not in text
