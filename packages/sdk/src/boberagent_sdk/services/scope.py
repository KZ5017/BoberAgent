"""Capability-facing scope validation interface."""

from typing import Protocol

from boberagent_contracts import AssetRef


class ScopeService(Protocol):
    """Read-only checks against the invocation's authorized Mission scope."""

    async def contains_asset(self, asset_ref: AssetRef) -> bool: ...

    async def assert_asset_allowed(self, asset_ref: AssetRef) -> None: ...

    async def contains_address(self, address: str) -> bool: ...

    async def assert_address_allowed(self, address: str) -> None: ...
