"""M20-B2 fixture acquisition stays behind SDK and never advertises public fetch."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from boberagent_contracts import CapabilityDefinition

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "capabilities/poc-source-acquisition/src"
MANIFEST = ROOT / "capabilities/poc-source-acquisition/capability.json"


def test_fixture_provider_uses_sdk_not_core_node_or_direct_network() -> None:
    banned = {
        "boberagent_core",
        "boberagent_execution_node",
        "boberagent_transport",
        "httpx",
        "requests",
        "urllib.request",
        "socket",
        "subprocess",
        "mcp",
    }
    violations: list[str] = []
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imports: list[str] = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports = [node.module]
            for name in imports:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in banned):
                    violations.append(f"{path.name}: {name}")
    assert violations == []


def test_advertised_provider_is_only_loopback_and_version_gated() -> None:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    definition = CapabilityDefinition.model_validate(raw["definition"])
    assert definition.capability_id == "poc.source_acquisition"
    assert definition.interaction_surfaces.internet_access is False
    assert definition.operations[0].execution_requirements["source_kind"] == "loopback_fixture"
    assert tuple((item.identifier, item.version_spec) for item in definition.dependencies) == (
        ("curl", ">=8.4,<9"),
    )
    assert raw["implementation"].startswith("boberagent_capability_poc_source_acquisition:")


def test_inventory_never_extracts_or_executes_repository_bytes() -> None:
    forbidden_calls = {"extract", "extractall", "exec", "eval", "__import__", "system", "Popen"}
    violations: list[str] = []
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name: str | None = None
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            if name in forbidden_calls:
                violations.append(f"{path.name}: {name}")
    assert violations == []
    production_source = "\\n".join(
        path.read_text(encoding="utf-8") for path in SOURCE.rglob("*.py")
    )
    assert "api.github.com" not in production_source
    assert "codeload.github.com" not in production_source
