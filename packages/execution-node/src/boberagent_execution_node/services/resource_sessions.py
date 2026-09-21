"""Run-bound dispatch across registered Node Resource and Session providers."""

from __future__ import annotations

from boberagent_contracts import (
    AccessMode,
    CapabilityRunRef,
    DomainRef,
    JsonObject,
    ResourceDescriptor,
    ResourceRef,
    SessionRef,
)
from boberagent_sdk import (
    ResourceLease,
    ResourceUnavailable,
    SessionHandle,
    SessionLease,
    SessionUnavailable,
)

from boberagent_execution_node.browser import BrowserRuntimeManager
from boberagent_execution_node.listener import (
    LISTENER_RESOURCE_TYPE,
    STREAM_SESSION_TYPE,
    ListenerRuntimeManager,
)
from boberagent_execution_node.persistence import RuntimeStore

_BROWSER_RESOURCE_TYPE = "browser_process"
_BROWSER_SESSION_TYPE = "browser"


class NodeResourceService:
    """Expose registered providers through the one generic SDK ResourceService."""

    def __init__(
        self,
        *,
        run_ref: CapabilityRunRef,
        store: RuntimeStore,
        browser: BrowserRuntimeManager,
        listener: ListenerRuntimeManager,
    ) -> None:
        self._store = store
        self._browser = browser.resource_service(run_ref)
        self._listener = listener.resource_service(run_ref)

    async def create(
        self,
        *,
        resource_type: str,
        configuration: JsonObject,
        owner_ref: DomainRef | None = None,
    ) -> ResourceDescriptor:
        if resource_type == _BROWSER_RESOURCE_TYPE:
            return await self._browser.create(
                resource_type=resource_type,
                configuration=configuration,
                owner_ref=owner_ref,
            )
        if resource_type == LISTENER_RESOURCE_TYPE:
            return await self._listener.create(
                resource_type=resource_type,
                configuration=configuration,
                owner_ref=owner_ref,
            )
        raise ResourceUnavailable(f"unsupported Resource type: {resource_type}")

    async def get(self, resource_ref: ResourceRef) -> ResourceDescriptor:
        provider = self._resource_type(resource_ref)
        if provider == _BROWSER_RESOURCE_TYPE:
            return await self._browser.get(resource_ref)
        if provider == LISTENER_RESOURCE_TYPE:
            return await self._listener.get(resource_ref)
        raise ResourceUnavailable(f"unsupported persisted Resource type: {provider}")

    def acquire(
        self,
        resource_ref: ResourceRef,
        *,
        mode: AccessMode = AccessMode.EXCLUSIVE,
    ) -> ResourceLease:
        provider = self._resource_type(resource_ref)
        if provider == _BROWSER_RESOURCE_TYPE:
            return self._browser.acquire(resource_ref, mode=mode)
        if provider == LISTENER_RESOURCE_TYPE:
            return self._listener.acquire(resource_ref, mode=mode)
        raise ResourceUnavailable(f"unsupported persisted Resource type: {provider}")

    async def release(self, lease: ResourceLease) -> None:
        await lease.release()

    async def close(self, resource_ref: ResourceRef) -> None:
        provider = self._resource_type(resource_ref)
        if provider == _BROWSER_RESOURCE_TYPE:
            await self._browser.close(resource_ref)
            return
        if provider == LISTENER_RESOURCE_TYPE:
            await self._listener.close(resource_ref)
            return
        raise ResourceUnavailable(f"unsupported persisted Resource type: {provider}")

    def _resource_type(self, resource_ref: ResourceRef) -> str:
        record = self._store.get_resource(resource_ref)
        if record is None:
            raise ResourceUnavailable(f"unknown Resource: {resource_ref}")
        return record.descriptor.resource_type


class NodeSessionService:
    """Expose semantic Session drivers without leaking provider implementation types."""

    def __init__(
        self,
        *,
        run_ref: CapabilityRunRef,
        store: RuntimeStore,
        browser: BrowserRuntimeManager,
        listener: ListenerRuntimeManager,
    ) -> None:
        self._store = store
        self._browser = browser.session_service(run_ref)
        self._listener = listener.session_service(run_ref)

    async def create(
        self,
        *,
        session_type: str,
        resource_refs: tuple[ResourceRef, ...],
        configuration: JsonObject,
        owner_ref: DomainRef | None = None,
        target_ref: DomainRef | None = None,
    ) -> SessionHandle:
        if session_type == _BROWSER_SESSION_TYPE:
            return await self._browser.create(
                session_type=session_type,
                resource_refs=resource_refs,
                configuration=configuration,
                owner_ref=owner_ref,
                target_ref=target_ref,
            )
        if session_type == STREAM_SESSION_TYPE:
            raise SessionUnavailable("TCP stream Sessions are created only by incoming connections")
        raise SessionUnavailable(f"unsupported Session type: {session_type}")

    async def get(self, session_ref: SessionRef) -> SessionHandle:
        provider = self._session_type(session_ref)
        if provider == _BROWSER_SESSION_TYPE:
            return await self._browser.get(session_ref)
        if provider == STREAM_SESSION_TYPE:
            return await self._listener.get(session_ref)
        raise SessionUnavailable(f"unsupported persisted Session type: {provider}")

    def acquire(
        self,
        session_ref: SessionRef,
        *,
        mode: AccessMode = AccessMode.EXCLUSIVE,
    ) -> SessionLease:
        provider = self._session_type(session_ref)
        if provider == _BROWSER_SESSION_TYPE:
            return self._browser.acquire(session_ref, mode=mode)
        if provider == STREAM_SESSION_TYPE:
            return self._listener.acquire(session_ref, mode=mode)
        raise SessionUnavailable(f"unsupported persisted Session type: {provider}")

    async def release(self, lease: SessionLease) -> None:
        await lease.release()

    async def close(self, session_ref: SessionRef) -> None:
        provider = self._session_type(session_ref)
        if provider == _BROWSER_SESSION_TYPE:
            await self._browser.close(session_ref)
            return
        if provider == STREAM_SESSION_TYPE:
            await self._listener.close(session_ref)
            return
        raise SessionUnavailable(f"unsupported persisted Session type: {provider}")

    def _session_type(self, session_ref: SessionRef) -> str:
        record = self._store.get_session(session_ref)
        if record is None:
            raise SessionUnavailable(f"unknown Session: {session_ref}")
        return record.descriptor.session_type
