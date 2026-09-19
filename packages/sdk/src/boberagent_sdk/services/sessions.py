"""Logical Session lookup and lease-safe driver access."""

from __future__ import annotations

import ipaddress
from types import TracebackType
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

from boberagent_contracts import (
    AccessMode,
    DomainRef,
    JsonObject,
    ResourceRef,
    SessionDescriptor,
    SessionRef,
)
from pydantic import BaseModel, ConfigDict, Field


class CommandResult(BaseModel):
    """Provider-neutral result for a command-capable Session driver."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exit_code: int | None = None
    stdout: bytes = b""
    stderr: bytes = b""


class SessionDriver(Protocol):
    """Base semantic driver surface; no provider internals are exposed."""

    @property
    def supported_operations(self) -> tuple[str, ...]: ...


class CommandSession(SessionDriver, Protocol):
    async def execute(self, command: str, *, timeout: float | None = None) -> CommandResult: ...


class BrowserUrl(BaseModel):
    """Validated HTTP(S) target used by browser scope enforcement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    scheme: str
    host: str
    port: int | None = Field(default=None, ge=1, le=65535)


class BrowserPageState(BaseModel):
    """Provider-neutral current page metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    final_url: str
    title: str
    status_code: int | None = Field(default=None, ge=100, le=599)


class BrowserInspection(BaseModel):
    """Bounded browser inspection data suitable for Artifact creation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page: BrowserPageState
    html: bytes


@runtime_checkable
class BrowserSession(SessionDriver, Protocol):
    """Semantic browser driver; no Playwright objects cross this boundary."""

    async def navigate(
        self,
        url: str,
        *,
        allowed_hosts: tuple[str, ...],
        timeout: float | None = None,
    ) -> BrowserPageState: ...

    async def inspect(self, *, max_html_bytes: int) -> BrowserInspection: ...


def parse_browser_url(url: str) -> BrowserUrl:
    """Normalize an HTTP(S) URL for deterministic host-based scope checks."""

    if not url or len(url) > 4096:
        raise ValueError("browser URL must contain between 1 and 4096 characters")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise ValueError("browser URL contains an invalid port or authority") from error
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("browser navigation supports only http and https URLs")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("browser URLs must not contain user information")
    if parsed.hostname is None:
        raise ValueError("browser URL must contain a hostname or IP address")
    host = normalize_browser_host(parsed.hostname)
    return BrowserUrl(url=url, scheme=scheme, host=host, port=port)


def normalize_browser_host(value: str) -> str:
    """Canonicalize a hostname, IPv4 address, or IPv6 address."""

    candidate = value.rstrip(".").lower()
    if not candidate:
        raise ValueError("browser URL host must not be empty")
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        try:
            return candidate.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise ValueError("browser URL contains an invalid hostname") from error


class SessionHandle:
    """Pair a logical descriptor with a semantic SDK driver."""

    __slots__ = ("_descriptor", "_driver")

    def __init__(self, descriptor: SessionDescriptor, driver: SessionDriver) -> None:
        self._descriptor = descriptor
        self._driver = driver

    @property
    def descriptor(self) -> SessionDescriptor:
        return self._descriptor

    @property
    def driver(self) -> SessionDriver:
        return self._driver


class SessionLease(Protocol):
    @property
    def handle(self) -> SessionHandle: ...

    @property
    def mode(self) -> AccessMode: ...

    async def release(self) -> None: ...

    async def __aenter__(self) -> SessionHandle: ...

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class SessionService(Protocol):
    async def create(
        self,
        *,
        session_type: str,
        resource_refs: tuple[ResourceRef, ...],
        configuration: JsonObject,
        owner_ref: DomainRef | None = None,
        target_ref: DomainRef | None = None,
    ) -> SessionHandle: ...

    async def get(self, session_ref: SessionRef) -> SessionHandle: ...

    def acquire(
        self,
        session_ref: SessionRef,
        *,
        mode: AccessMode = AccessMode.EXCLUSIVE,
    ) -> SessionLease: ...

    async def release(self, lease: SessionLease) -> None: ...

    async def close(self, session_ref: SessionRef) -> None: ...
