"""Static tests for the platform package dependency direction."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

PACKAGE_SOURCE_ROOTS = {
    "boberagent_contracts": REPOSITORY_ROOT / "packages/contracts/src/boberagent_contracts",
    "boberagent_sdk": REPOSITORY_ROOT / "packages/sdk/src/boberagent_sdk",
    "boberagent_core": REPOSITORY_ROOT / "packages/core/src/boberagent_core",
    "boberagent_execution_node": (
        REPOSITORY_ROOT / "packages/execution-node/src/boberagent_execution_node"
    ),
    "boberagent_transport": REPOSITORY_ROOT / "packages/transport/src/boberagent_transport",
    "boberagent_transport_mcp": (
        REPOSITORY_ROOT / "packages/transport-mcp/src/boberagent_transport_mcp"
    ),
}

FORBIDDEN_IMPORTS = {
    "boberagent_contracts": frozenset(
        {
            "boberagent_core",
            "boberagent_sdk",
            "boberagent_execution_node",
            "boberagent_transport",
            "mcp",
            "sqlalchemy",
        }
    ),
    "boberagent_sdk": frozenset(
        {
            "alembic",
            "boberagent_core",
            "boberagent_execution_node",
            "boberagent_transport",
            "mcp",
            "sqlalchemy",
        }
    ),
    "boberagent_core": frozenset(
        {
            "boberagent_execution_node",
            "boberagent_sdk",
            "mcp",
        }
    ),
    "boberagent_execution_node": frozenset({"boberagent_core", "mcp"}),
    "boberagent_transport": frozenset(
        {
            "boberagent_core",
            "boberagent_execution_node",
            "boberagent_sdk",
            "mcp",
            "httpx2",
            "sqlalchemy",
            "uvicorn",
        }
    ),
    "boberagent_transport_mcp": frozenset(
        {
            "alembic",
            "boberagent_core",
            "boberagent_execution_node",
            "boberagent_sdk",
            "sqlalchemy",
        }
    ),
}

CAPABILITY_SOURCE_ROOTS = tuple(
    sorted(path for path in (REPOSITORY_ROOT / "capabilities").glob("*/src") if path.is_dir())
)
CAPABILITY_FORBIDDEN_IMPORTS = frozenset(
    {
        "alembic",
        "boberagent_core",
        "boberagent_execution_node",
        "boberagent_transport",
        "mcp",
        "sqlalchemy",
        "subprocess",
    }
)


def _python_files(source_root: Path) -> Iterator[Path]:
    yield from sorted(source_root.rglob("*.py"))


def _imports_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)

    return imports


def _matches_package(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


@pytest.mark.parametrize("package_name", sorted(FORBIDDEN_IMPORTS))
def test_package_does_not_import_forbidden_dependencies(package_name: str) -> None:
    source_root = PACKAGE_SOURCE_ROOTS[package_name]
    forbidden = FORBIDDEN_IMPORTS[package_name]
    violations: list[str] = []

    for path in _python_files(source_root):
        for imported_module in sorted(_imports_in(path)):
            imports_capability_implementation = (
                package_name == "boberagent_core"
                and imported_module.startswith("boberagent_capability_")
            )
            if imports_capability_implementation or any(
                _matches_package(imported_module, dependency) for dependency in forbidden
            ):
                relative_path = path.relative_to(REPOSITORY_ROOT)
                violations.append(f"{relative_path}: imports {imported_module}")

    assert not violations, "Forbidden package imports found:\n" + "\n".join(violations)


@pytest.mark.parametrize("source_root", CAPABILITY_SOURCE_ROOTS, ids=lambda path: path.parent.name)
def test_capability_package_uses_only_sdk_boundary(source_root: Path) -> None:
    violations: list[str] = []
    for path in _python_files(source_root):
        for imported_module in sorted(_imports_in(path)):
            if any(
                _matches_package(imported_module, dependency)
                for dependency in CAPABILITY_FORBIDDEN_IMPORTS
            ):
                relative_path = path.relative_to(REPOSITORY_ROOT)
                violations.append(f"{relative_path}: imports {imported_module}")

    assert not violations, "Forbidden capability imports found:\n" + "\n".join(violations)


def test_workflow_engine_uses_only_core_and_neutral_transport_boundaries() -> None:
    source_root = PACKAGE_SOURCE_ROOTS["boberagent_core"] / "workflows"
    forbidden = frozenset(
        {
            "boberagent_capability_",
            "boberagent_execution_node",
            "boberagent_transport_mcp",
            "mcp",
        }
    )
    violations: list[str] = []
    for path in _python_files(source_root):
        for imported_module in sorted(_imports_in(path)):
            if any(imported_module.startswith(dependency) for dependency in forbidden):
                relative_path = path.relative_to(REPOSITORY_ROOT)
                violations.append(f"{relative_path}: imports {imported_module}")

    assert not violations, "Workflow boundary violations found:\n" + "\n".join(violations)
