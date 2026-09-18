"""Smoke tests for independently installable workspace package roots."""

from __future__ import annotations

import importlib

import pytest

PACKAGE_ROOTS = (
    "boberagent_contracts",
    "boberagent_sdk",
    "boberagent_core",
    "boberagent_execution_node",
    "boberagent_transport",
    "boberagent_transport_mcp",
    "boberagent_capability_network_service_discovery",
)


@pytest.mark.parametrize("package_name", PACKAGE_ROOTS)
def test_package_root_imports(package_name: str) -> None:
    module = importlib.import_module(package_name)

    assert module.__name__ == package_name
