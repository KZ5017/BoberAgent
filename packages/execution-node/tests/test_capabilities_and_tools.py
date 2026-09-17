"""Capability discovery isolation and local dependency resolution tests."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from boberagent_contracts import DependencyDeclaration, DependencyType
from boberagent_execution_node.capabilities import (
    CapabilityAvailability,
    CapabilityLoader,
    CapabilityLoadError,
    LocalCapabilityRegistry,
)
from boberagent_execution_node.config import ToolConfiguration
from boberagent_execution_node.tools import (
    DependencyResolver,
    ToolAvailability,
    ToolRegistry,
)
from boberagent_execution_node_test_capabilities import (
    SyntheticCapability,
    capability_definition,
    capability_manifest,
)
from boberagent_sdk import DependencyError


def _write_manifest(directory: Path, manifest: dict[str, object]) -> None:
    directory.mkdir(parents=True)
    (directory / "capability.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def test_loader_isolates_broken_and_duplicate_providers(tmp_path: Path) -> None:
    _write_manifest(tmp_path / "01-valid", capability_manifest())
    _write_manifest(tmp_path / "02-duplicate", capability_manifest())
    _write_manifest(
        tmp_path / "03-broken",
        capability_manifest(
            capability_id="test.broken_provider",
            implementation="missing_test_provider:Capability",
            operations=("run",),
        ),
    )
    registry = LocalCapabilityRegistry()

    loaded = CapabilityLoader().discover((tmp_path,), registry)

    assert len(loaded) == 2
    assert any("duplicate capability ID" in failure for failure in registry.failures)
    valid = registry.get("test.synthetic_runtime")
    assert isinstance(valid.load_implementation(), SyntheticCapability)
    broken = registry.get("test.broken_provider")
    with pytest.raises(CapabilityLoadError, match="could not load"):
        broken.load_implementation()
    assert broken.availability is CapabilityAvailability.UNAVAILABLE
    assert valid.availability is CapabilityAvailability.AVAILABLE


def test_tool_registry_and_dependency_resolver(tmp_path: Path) -> None:
    del tmp_path
    tools = ToolRegistry()
    tools.register(
        "python",
        ToolConfiguration(executable=sys.executable, version_args=("--version",)),
    )
    tools.register("missing", ToolConfiguration(executable="definitely-not-a-real-tool"))
    asyncio.run(tools.refresh())

    python = tools.get("python")
    assert python.availability is ToolAvailability.AVAILABLE
    assert python.resolved_path == Path(sys.executable).resolve()
    assert python.version is not None
    assert tools.get("missing").availability is ToolAvailability.UNAVAILABLE

    registry = LocalCapabilityRegistry()
    resolver = DependencyResolver(tools, registry)
    available_definition = capability_definition(
        dependencies=(
            DependencyDeclaration(
                dependency_type=DependencyType.TOOL,
                identifier="python",
                version_spec=">=3.12",
            ),
        )
    )
    assert resolver.require(available_definition).satisfied

    missing_definition = capability_definition(
        dependencies=(
            DependencyDeclaration(
                dependency_type=DependencyType.TOOL,
                identifier="missing",
            ),
        )
    )
    report = resolver.evaluate(missing_definition)
    assert report.missing_required == ("tool:missing",)
    with pytest.raises(DependencyError, match="tool:missing"):
        resolver.require(missing_definition)
