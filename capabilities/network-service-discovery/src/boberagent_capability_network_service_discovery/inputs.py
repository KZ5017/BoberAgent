"""Typed semantic inputs for network service discovery."""

from boberagent_contracts import AssetRef
from pydantic import BaseModel, ConfigDict, Field

from .profiles import ScanProfile


class ServiceDiscoveryInput(BaseModel):
    """One-Asset discovery request without provider-specific command syntax."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_ref: AssetRef
    profile: ScanProfile = ScanProfile.STANDARD
    timeout_seconds: float = Field(default=600.0, gt=0, le=3600)
