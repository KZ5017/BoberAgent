"""Small read-only snapshots resolved through the EntityReader boundary."""

from typing import Protocol

from boberagent_contracts import AssetRef, DomainRef, JsonObject
from pydantic import BaseModel, ConfigDict, Field


class EntitySnapshot(BaseModel):
    """Extensible SDK-owned snapshot without Core persistence identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    ref: DomainRef
    kind: str = Field(min_length=1, max_length=64)
    attributes: JsonObject = Field(default_factory=dict)


class AssetSnapshot(BaseModel):
    """Minimal Asset view needed by target-oriented capability implementations."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    ref: AssetRef
    primary_address: str = Field(min_length=1, max_length=255)
    addresses: tuple[str, ...] = ()
    metadata: JsonObject = Field(default_factory=dict)


class EntityReader(Protocol):
    """Controlled read-only resolution of references supplied to a capability."""

    async def get(self, ref: DomainRef) -> EntitySnapshot | AssetSnapshot: ...

    async def asset(self, asset_ref: AssetRef) -> AssetSnapshot: ...
