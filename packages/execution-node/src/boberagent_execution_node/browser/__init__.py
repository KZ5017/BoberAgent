"""Managed browser Resource and Session provider."""

from .backend import BrowserBackend, PlaywrightBrowserBackend
from .service import BrowserResourceService, BrowserRuntimeManager, BrowserSessionService

__all__ = [
    "BrowserBackend",
    "BrowserResourceService",
    "BrowserRuntimeManager",
    "BrowserSessionService",
    "PlaywrightBrowserBackend",
]
