"""Capability-facing Resource operations and lease semantics."""

from types import TracebackType
from typing import Protocol

from boberagent_contracts import (
    AccessMode,
    DomainRef,
    JsonObject,
    ResourceDescriptor,
    ResourceRef,
)


class ResourceLease(Protocol):
    @property
    def descriptor(self) -> ResourceDescriptor: ...

    @property
    def mode(self) -> AccessMode: ...

    async def release(self) -> None: ...

    async def __aenter__(self) -> ResourceDescriptor: ...

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class ResourceService(Protocol):
    async def create(
        self,
        *,
        resource_type: str,
        configuration: JsonObject,
        owner_ref: DomainRef | None = None,
    ) -> ResourceDescriptor: ...

    async def get(self, resource_ref: ResourceRef) -> ResourceDescriptor: ...

    def acquire(
        self,
        resource_ref: ResourceRef,
        *,
        mode: AccessMode = AccessMode.EXCLUSIVE,
    ) -> ResourceLease: ...

    async def release(self, lease: ResourceLease) -> None: ...

    async def close(self, resource_ref: ResourceRef) -> None: ...
