"""Public browser interaction capability surface."""

from .capability import BrowserInteractionCapability
from .inputs import (
    CloseBrowserInput,
    InspectBrowserInput,
    NavigateBrowserInput,
    OpenBrowserInput,
)

__all__ = [
    "BrowserInteractionCapability",
    "CloseBrowserInput",
    "InspectBrowserInput",
    "NavigateBrowserInput",
    "OpenBrowserInput",
]
