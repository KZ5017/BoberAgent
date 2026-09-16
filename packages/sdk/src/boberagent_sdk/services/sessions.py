"""Logical Session lookup and lease-safe driver access."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol

from boberagent_contracts import AccessMode, SessionDescriptor, SessionRef
from pydantic import BaseModel, ConfigDict


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
    async def get(self, session_ref: SessionRef) -> SessionHandle: ...

    def acquire(
        self,
        session_ref: SessionRef,
        *,
        mode: AccessMode = AccessMode.EXCLUSIVE,
    ) -> SessionLease: ...

    async def release(self, lease: SessionLease) -> None: ...
