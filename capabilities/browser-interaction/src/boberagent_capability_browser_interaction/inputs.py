"""Validated semantic inputs for ``browser.interaction`` operations."""

from boberagent_contracts import AssetRef, SessionRef
from pydantic import BaseModel, ConfigDict, Field


class BrowserInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_ref: AssetRef


class OpenBrowserInput(BrowserInput):
    pass


class NavigateBrowserInput(BrowserInput):
    session_ref: SessionRef
    url: str = Field(min_length=1, max_length=4096)
    timeout_seconds: float = Field(default=30, gt=0, le=120)


class InspectBrowserInput(BrowserInput):
    session_ref: SessionRef
    max_html_bytes: int = Field(default=1024 * 1024, ge=1, le=2 * 1024 * 1024)


class CloseBrowserInput(BrowserInput):
    session_ref: SessionRef
