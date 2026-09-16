"""Controlled scope and entity-reader behavior."""

import asyncio

import pytest
from boberagent_contracts import AssetRef, ServiceRef
from boberagent_sdk import AssetSnapshot, DependencyError, ScopeViolation
from boberagent_sdk.testing import FakeExecutionContext


def test_allowed_and_denied_assets() -> None:
    context = FakeExecutionContext()
    allowed = AssetRef("asset-allowed")
    denied = AssetRef("asset-denied")
    context.scope.allow_asset(allowed)
    try:
        asyncio.run(context.scope.assert_asset_allowed(allowed))
        assert asyncio.run(context.scope.contains_asset(allowed))
        with pytest.raises(ScopeViolation, match="asset-denied"):
            asyncio.run(context.scope.assert_asset_allowed(denied))
    finally:
        context.close()


def test_registered_asset_resolves_without_mutation_api() -> None:
    context = FakeExecutionContext()
    asset = AssetSnapshot(
        ref=AssetRef("asset-one"),
        primary_address="192.0.2.10",
        addresses=("192.0.2.10", "example.test"),
        metadata={"environment": "lab"},
    )
    context.entities.add(asset)
    try:
        assert asyncio.run(context.entities.asset(asset.ref)) == asset
        assert not hasattr(context.entities, "update")
        assert not hasattr(context.entities, "delete")
        with pytest.raises(DependencyError, match="service-missing"):
            asyncio.run(context.entities.get(ServiceRef("service-missing")))
    finally:
        context.close()
