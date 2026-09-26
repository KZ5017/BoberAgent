"""M20-B1 acquisition state is Core-owned; shared types have no infrastructure imports."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACQUISITIONS = ROOT / "packages/core/src/boberagent_core/acquisitions"
CONTRACTS = ROOT / "packages/contracts/src/boberagent_contracts"
INDEPENDENT = (
    CONTRACTS,
    ROOT / "packages/sdk/src",
    ROOT / "packages/execution-node/src",
    ROOT / "packages/transport/src",
)


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return tuple(names)


def test_core_acquisition_has_no_download_or_node_runtime_dependency() -> None:
    banned = (
        "boberagent_execution_node",
        "boberagent_transport_mcp",
        "boberagent_capability_",
        "boberagent_core.research.providers.github",
        "httpx",
        "urllib.request",
        "subprocess",
        "zipfile",
    )
    violations = [
        f"{path}: {name}"
        for path in ACQUISITIONS.rglob("*.py")
        for name in _imports(path)
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in banned)
    ]
    assert not violations, violations


def test_non_core_packages_do_not_import_acquisition_domain() -> None:
    violations = [
        f"{path}: {name}"
        for directory in INDEPENDENT
        for path in directory.rglob("*.py")
        for name in _imports(path)
        if name.startswith("boberagent_core.acquisitions")
        or name.startswith("boberagent_core.research")
    ]
    assert not violations, violations


def test_contract_acquisition_schema_imports_no_core_or_infrastructure() -> None:
    path = CONTRACTS / "poc_acquisition.py"
    banned = ("boberagent_core", "sqlalchemy", "alembic", "httpx", "mcp")
    assert not [
        name
        for name in _imports(path)
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in banned)
    ]
