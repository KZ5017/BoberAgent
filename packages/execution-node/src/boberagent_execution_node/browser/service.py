"""Node-owned durable browser Resource and Session lifecycle services."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Literal, Protocol
from uuid import uuid4

from boberagent_contracts import (
    AccessMode,
    CapabilityRunRef,
    DomainRef,
    JsonObject,
    ResourceDescriptor,
    ResourceRef,
    SessionDescriptor,
    SessionRef,
)
from boberagent_sdk import (
    ResourceLease,
    ResourceUnavailable,
    SessionHandle,
    SessionLease,
    SessionUnavailable,
)
from pydantic import BaseModel, ConfigDict, ValidationError

from boberagent_execution_node.persistence import (
    ResourceRuntimeRecord,
    ResourceRuntimeState,
    RuntimeStore,
    SessionRuntimeRecord,
    SessionRuntimeState,
)

from .backend import BrowserBackend, ManagedBrowserRuntime, ManagedBrowserSession

_RESOURCE_TYPE = "browser_process"
_SESSION_TYPE = "browser"
_PROVIDER = "playwright.chromium"


class BrowserResourceConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    headless: Literal[True] = True


class BrowserSessionConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BrowserToolRecord(Protocol):
    @property
    def resolved_path(self) -> Path | None: ...


class BrowserToolRegistry(Protocol):
    def get(self, name: str) -> BrowserToolRecord: ...


class BrowserRuntimeManager:
    """Manage the first concrete Resource/Session provider with one Session per Resource."""

    def __init__(
        self,
        *,
        store: RuntimeStore,
        tools: BrowserToolRegistry,
        backend: BrowserBackend,
        clock: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._tools = tools
        self._backend = backend
        self._clock = clock
        self._resources: dict[str, ManagedBrowserRuntime] = {}
        self._sessions: dict[str, ManagedBrowserSession] = {}
        self._resource_locks: dict[str, asyncio.Lock] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}

    def resource_service(self, run_ref: CapabilityRunRef) -> BrowserResourceService:
        return BrowserResourceService(self, run_ref)

    def session_service(self, run_ref: CapabilityRunRef) -> BrowserSessionService:
        return BrowserSessionService(self, run_ref)

    async def create_resource(
        self,
        *,
        run_ref: CapabilityRunRef,
        resource_type: str,
        configuration: JsonObject,
        owner_ref: DomainRef | None,
    ) -> ResourceDescriptor:
        if resource_type != _RESOURCE_TYPE:
            raise ResourceUnavailable(f"unsupported Resource type: {resource_type}")
        effective_owner = owner_ref or run_ref
        if str(effective_owner) not in self._allowed_owners(run_ref):
            raise ResourceUnavailable("Resource owner is outside the current invocation provenance")
        try:
            parsed = BrowserResourceConfiguration.model_validate(configuration)
        except ValidationError as error:
            raise ResourceUnavailable("invalid browser Resource configuration") from error
        now = self._clock()
        resource_ref = ResourceRef(f"resource-browser-{uuid4()}")
        descriptor = ResourceDescriptor(
            resource_id=resource_ref,
            resource_type=_RESOURCE_TYPE,
            provider=_PROVIDER,
            state=ResourceRuntimeState.CREATING.value,
            owner_ref=effective_owner,
            created_by_run=run_ref,
            created_at=now,
            access_modes=(AccessMode.EXCLUSIVE,),
            lifecycle_metadata={
                "headless": parsed.headless,
                "last_activity_at": now.isoformat(),
            },
        )
        self._store.add_resource(
            ResourceRuntimeRecord(
                descriptor=descriptor,
                updated_at=now,
                last_activity_at=now,
            )
        )
        try:
            tool = self._tools.get("chromium")
            if tool.resolved_path is None:
                raise ResourceUnavailable("configured Chromium executable is unavailable")
            runtime = await self._backend.launch(
                executable_path=tool.resolved_path,
                headless=parsed.headless,
            )
        except Exception as error:
            self._store.update_resource_state(
                resource_ref, ResourceRuntimeState.FAILED, self._clock()
            )
            if isinstance(error, ResourceUnavailable):
                raise
            raise ResourceUnavailable("browser Resource creation failed") from error
        self._resources[str(resource_ref)] = runtime
        self._store.update_resource_state(resource_ref, ResourceRuntimeState.READY, self._clock())
        return self._resource_descriptor(resource_ref)

    def get_resource(self, resource_ref: ResourceRef) -> ResourceDescriptor:
        return self._resource_descriptor(resource_ref)

    def acquire_resource(
        self,
        resource_ref: ResourceRef,
        mode: AccessMode,
    ) -> ResourceLease:
        descriptor = self._resource_descriptor(resource_ref)
        if mode not in descriptor.access_modes:
            raise ResourceUnavailable(f"Resource does not support {mode}: {resource_ref}")
        return _BrowserResourceLease(self, resource_ref, mode)

    async def close_resource(self, resource_ref: ResourceRef) -> None:
        record = self._require_resource(resource_ref)
        state = ResourceRuntimeState(record.descriptor.state)
        if state in {ResourceRuntimeState.CLOSED, ResourceRuntimeState.LOST}:
            return
        lock = self._resource_locks.setdefault(str(resource_ref), asyncio.Lock())
        async with lock:
            record = self._require_resource(resource_ref)
            state = ResourceRuntimeState(record.descriptor.state)
            if state in {ResourceRuntimeState.CLOSED, ResourceRuntimeState.LOST}:
                return
            self._store.update_resource_state(
                resource_ref, ResourceRuntimeState.CLOSING, self._clock()
            )
            for session in self._store.list_sessions_for_resource(resource_ref):
                await self.close_session(session.descriptor.session_id)
            runtime = self._resources.pop(str(resource_ref), None)
            try:
                if runtime is not None:
                    await runtime.close()
            except Exception as error:
                self._store.update_resource_state(
                    resource_ref, ResourceRuntimeState.FAILED, self._clock()
                )
                raise ResourceUnavailable("browser Resource close failed") from error
            self._store.update_resource_state(
                resource_ref, ResourceRuntimeState.CLOSED, self._clock()
            )

    async def create_session(
        self,
        *,
        run_ref: CapabilityRunRef,
        session_type: str,
        resource_refs: tuple[ResourceRef, ...],
        configuration: JsonObject,
        owner_ref: DomainRef | None,
        target_ref: DomainRef | None,
    ) -> SessionHandle:
        if session_type != _SESSION_TYPE:
            raise SessionUnavailable(f"unsupported Session type: {session_type}")
        if len(resource_refs) != 1:
            raise SessionUnavailable("browser Session requires exactly one browser Resource")
        effective_owner = owner_ref or run_ref
        if str(effective_owner) not in self._allowed_owners(run_ref):
            raise SessionUnavailable("Session owner is outside the current invocation provenance")
        try:
            BrowserSessionConfiguration.model_validate(configuration)
        except ValidationError as error:
            raise SessionUnavailable("invalid browser Session configuration") from error
        resource_ref = resource_refs[0]
        resource = self._require_resource(resource_ref)
        self.assert_resource_access(resource_ref, run_ref)
        if ResourceRuntimeState(resource.descriptor.state) is not ResourceRuntimeState.READY:
            raise SessionUnavailable("backing browser Resource is not ready")
        runtime = self._resources.get(str(resource_ref))
        if runtime is None:
            raise SessionUnavailable("backing browser Resource has no live runtime")
        active = {
            SessionRuntimeState.CREATING.value,
            SessionRuntimeState.ACTIVE.value,
            SessionRuntimeState.CLOSING.value,
        }
        if any(
            record.descriptor.state in active
            for record in self._store.list_sessions_for_resource(resource_ref)
        ):
            raise SessionUnavailable("browser Resource already owns a live Session")
        now = self._clock()
        session_ref = SessionRef(f"session-browser-{uuid4()}")
        descriptor = SessionDescriptor(
            session_id=session_ref,
            session_type=_SESSION_TYPE,
            state=SessionRuntimeState.CREATING.value,
            provider=_PROVIDER,
            owner_ref=effective_owner,
            created_by_run=run_ref,
            created_at=now,
            target_ref=target_ref,
            resource_refs=(resource_ref,),
            supported_operations=("navigate", "inspect"),
            access_modes=(AccessMode.EXCLUSIVE,),
            lifecycle_metadata={"last_activity_at": now.isoformat()},
        )
        self._store.add_session(
            SessionRuntimeRecord(
                descriptor=descriptor,
                updated_at=now,
                last_activity_at=now,
            )
        )
        try:
            driver = await runtime.create_session()
        except Exception as error:
            self._store.update_session_state(session_ref, SessionRuntimeState.FAILED, self._clock())
            raise SessionUnavailable("browser Session creation failed") from error
        self._sessions[str(session_ref)] = driver
        self._store.update_session_state(session_ref, SessionRuntimeState.ACTIVE, self._clock())
        return self.get_session(session_ref)

    def get_session(self, session_ref: SessionRef) -> SessionHandle:
        record = self._require_session(session_ref)
        driver = self._sessions.get(str(session_ref), _UnavailableBrowserDriver())
        return SessionHandle(record.descriptor, driver)

    def acquire_session(self, session_ref: SessionRef, mode: AccessMode) -> SessionLease:
        record = self._require_session(session_ref)
        if mode not in record.descriptor.access_modes:
            raise SessionUnavailable(f"Session does not support {mode}: {session_ref}")
        if SessionRuntimeState(record.descriptor.state) is not SessionRuntimeState.ACTIVE:
            raise SessionUnavailable(f"Session is not active: {session_ref}")
        self._require_live_session_resource(record)
        if str(session_ref) not in self._sessions:
            raise SessionUnavailable(f"Session has no live browser driver: {session_ref}")
        return _BrowserSessionLease(self, session_ref, mode)

    async def close_session(self, session_ref: SessionRef) -> None:
        record = self._require_session(session_ref)
        state = SessionRuntimeState(record.descriptor.state)
        if state in {SessionRuntimeState.CLOSED, SessionRuntimeState.LOST}:
            return
        lock = self._session_locks.setdefault(str(session_ref), asyncio.Lock())
        async with lock:
            record = self._require_session(session_ref)
            state = SessionRuntimeState(record.descriptor.state)
            if state in {SessionRuntimeState.CLOSED, SessionRuntimeState.LOST}:
                return
            self._store.update_session_state(
                session_ref, SessionRuntimeState.CLOSING, self._clock()
            )
            driver = self._sessions.pop(str(session_ref), None)
            try:
                if driver is not None:
                    await driver.close()
            except Exception as error:
                self._store.update_session_state(
                    session_ref, SessionRuntimeState.FAILED, self._clock()
                )
                raise SessionUnavailable("browser Session close failed") from error
            self._store.update_session_state(session_ref, SessionRuntimeState.CLOSED, self._clock())

    async def shutdown(self) -> None:
        for resource_ref in tuple(ResourceRef(value) for value in self._resources):
            await self.close_resource(resource_ref)

    def _require_resource(self, resource_ref: ResourceRef) -> ResourceRuntimeRecord:
        record = self._store.get_resource(resource_ref)
        if record is None:
            raise ResourceUnavailable(f"unknown Resource: {resource_ref}")
        if record.descriptor.resource_type != _RESOURCE_TYPE:
            raise ResourceUnavailable(f"Resource is not a browser Resource: {resource_ref}")
        return record

    def _resource_descriptor(self, resource_ref: ResourceRef) -> ResourceDescriptor:
        return self._require_resource(resource_ref).descriptor

    def _require_session(self, session_ref: SessionRef) -> SessionRuntimeRecord:
        record = self._store.get_session(session_ref)
        if record is None:
            raise SessionUnavailable(f"unknown Session: {session_ref}")
        if record.descriptor.session_type != _SESSION_TYPE:
            raise SessionUnavailable(f"Session is not a browser Session: {session_ref}")
        return record

    def _require_live_session_resource(self, record: SessionRuntimeRecord) -> ResourceRef:
        if len(record.descriptor.resource_refs) != 1:
            raise SessionUnavailable("browser Session has invalid Resource ownership metadata")
        resource_ref = record.descriptor.resource_refs[0]
        try:
            resource = self._require_resource(resource_ref)
        except ResourceUnavailable as error:
            raise SessionUnavailable("backing browser Resource is unavailable") from error
        if ResourceRuntimeState(resource.descriptor.state) is not ResourceRuntimeState.READY:
            raise SessionUnavailable("backing browser Resource is not ready")
        if str(resource_ref) not in self._resources:
            raise SessionUnavailable("backing browser Resource has no live runtime")
        return resource_ref

    def assert_resource_access(self, resource_ref: ResourceRef, run_ref: CapabilityRunRef) -> None:
        descriptor = self._require_resource(resource_ref).descriptor
        if str(descriptor.owner_ref) not in self._allowed_owners(run_ref):
            raise ResourceUnavailable("Resource is not owned by this invocation provenance")

    def assert_session_access(self, session_ref: SessionRef, run_ref: CapabilityRunRef) -> None:
        descriptor = self._require_session(session_ref).descriptor
        if str(descriptor.owner_ref) not in self._allowed_owners(run_ref):
            raise SessionUnavailable("Session is not owned by this invocation provenance")

    def _allowed_owners(self, run_ref: CapabilityRunRef) -> frozenset[str]:
        run = self._store.get_run(run_ref)
        if run is None:
            raise RuntimeError(f"unknown CapabilityRun for Resource/Session access: {run_ref}")
        owners = {str(run_ref), str(run.mission_ref)}
        if run.workflow_run_ref is not None:
            owners.add(str(run.workflow_run_ref))
        return frozenset(owners)

    async def _enter_resource(
        self, resource_ref: ResourceRef, mode: AccessMode
    ) -> ResourceDescriptor:
        lock = self._resource_locks.setdefault(str(resource_ref), asyncio.Lock())
        await lock.acquire()
        try:
            record = self._require_resource(resource_ref)
            if ResourceRuntimeState(record.descriptor.state) is not ResourceRuntimeState.READY:
                raise ResourceUnavailable(f"Resource is not ready: {resource_ref}")
            return record.descriptor
        except BaseException:
            lock.release()
            raise

    def _release_resource(self, resource_ref: ResourceRef) -> None:
        self._store.touch_resource(resource_ref, self._clock())
        self._resource_locks[str(resource_ref)].release()

    async def _enter_session(self, session_ref: SessionRef, mode: AccessMode) -> SessionHandle:
        lock = self._session_locks.setdefault(str(session_ref), asyncio.Lock())
        await lock.acquire()
        try:
            record = self._require_session(session_ref)
            if SessionRuntimeState(record.descriptor.state) is not SessionRuntimeState.ACTIVE:
                raise SessionUnavailable(f"Session is not active: {session_ref}")
            self._require_live_session_resource(record)
            driver = self._sessions.get(str(session_ref))
            if driver is None:
                raise SessionUnavailable(f"Session has no live browser driver: {session_ref}")
            return SessionHandle(record.descriptor, driver)
        except BaseException:
            lock.release()
            raise

    def _release_session(self, session_ref: SessionRef) -> None:
        record = self._require_session(session_ref)
        now = self._clock()
        self._store.touch_session(session_ref, now)
        for resource_ref in record.descriptor.resource_refs:
            self._store.touch_resource(resource_ref, now)
        self._session_locks[str(session_ref)].release()


class BrowserResourceService:
    def __init__(self, manager: BrowserRuntimeManager, run_ref: CapabilityRunRef) -> None:
        self._manager = manager
        self._run_ref = run_ref

    async def create(
        self,
        *,
        resource_type: str,
        configuration: JsonObject,
        owner_ref: DomainRef | None = None,
    ) -> ResourceDescriptor:
        return await self._manager.create_resource(
            run_ref=self._run_ref,
            resource_type=resource_type,
            configuration=configuration,
            owner_ref=owner_ref,
        )

    async def get(self, resource_ref: ResourceRef) -> ResourceDescriptor:
        self._manager.assert_resource_access(resource_ref, self._run_ref)
        return self._manager.get_resource(resource_ref)

    def acquire(
        self,
        resource_ref: ResourceRef,
        *,
        mode: AccessMode = AccessMode.EXCLUSIVE,
    ) -> ResourceLease:
        self._manager.assert_resource_access(resource_ref, self._run_ref)
        return self._manager.acquire_resource(resource_ref, mode)

    async def release(self, lease: ResourceLease) -> None:
        await lease.release()

    async def close(self, resource_ref: ResourceRef) -> None:
        self._manager.assert_resource_access(resource_ref, self._run_ref)
        await self._manager.close_resource(resource_ref)


class BrowserSessionService:
    def __init__(self, manager: BrowserRuntimeManager, run_ref: CapabilityRunRef) -> None:
        self._manager = manager
        self._run_ref = run_ref

    async def create(
        self,
        *,
        session_type: str,
        resource_refs: tuple[ResourceRef, ...],
        configuration: JsonObject,
        owner_ref: DomainRef | None = None,
        target_ref: DomainRef | None = None,
    ) -> SessionHandle:
        return await self._manager.create_session(
            run_ref=self._run_ref,
            session_type=session_type,
            resource_refs=resource_refs,
            configuration=configuration,
            owner_ref=owner_ref,
            target_ref=target_ref,
        )

    async def get(self, session_ref: SessionRef) -> SessionHandle:
        self._manager.assert_session_access(session_ref, self._run_ref)
        return self._manager.get_session(session_ref)

    def acquire(
        self,
        session_ref: SessionRef,
        *,
        mode: AccessMode = AccessMode.EXCLUSIVE,
    ) -> SessionLease:
        self._manager.assert_session_access(session_ref, self._run_ref)
        return self._manager.acquire_session(session_ref, mode)

    async def release(self, lease: SessionLease) -> None:
        await lease.release()

    async def close(self, session_ref: SessionRef) -> None:
        self._manager.assert_session_access(session_ref, self._run_ref)
        await self._manager.close_session(session_ref)


class _BrowserResourceLease:
    def __init__(
        self,
        manager: BrowserRuntimeManager,
        resource_ref: ResourceRef,
        mode: AccessMode,
    ) -> None:
        self._manager = manager
        self._resource_ref = resource_ref
        self._mode = mode
        self._entered = False

    @property
    def descriptor(self) -> ResourceDescriptor:
        return self._manager.get_resource(self._resource_ref)

    @property
    def mode(self) -> AccessMode:
        return self._mode

    async def __aenter__(self) -> ResourceDescriptor:
        if not self._entered:
            descriptor = await self._manager._enter_resource(self._resource_ref, self._mode)
            self._entered = True
            return descriptor
        return self.descriptor

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback
        await self.release()

    async def release(self) -> None:
        if self._entered:
            self._manager._release_resource(self._resource_ref)
            self._entered = False


class _BrowserSessionLease:
    def __init__(
        self,
        manager: BrowserRuntimeManager,
        session_ref: SessionRef,
        mode: AccessMode,
    ) -> None:
        self._manager = manager
        self._session_ref = session_ref
        self._mode = mode
        self._entered = False

    @property
    def handle(self) -> SessionHandle:
        return self._manager.get_session(self._session_ref)

    @property
    def mode(self) -> AccessMode:
        return self._mode

    async def __aenter__(self) -> SessionHandle:
        if not self._entered:
            handle = await self._manager._enter_session(self._session_ref, self._mode)
            self._entered = True
            return handle
        return self.handle

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback
        await self.release()

    async def release(self) -> None:
        if self._entered:
            self._manager._release_session(self._session_ref)
            self._entered = False


class _UnavailableBrowserDriver:
    @property
    def supported_operations(self) -> tuple[str, ...]:
        return ("navigate", "inspect")

    async def navigate(
        self,
        url: str,
        *,
        allowed_hosts: tuple[str, ...],
        timeout: float | None = None,
    ) -> object:
        del url, allowed_hosts, timeout
        raise SessionUnavailable("browser Session has no live driver")

    async def inspect(self, *, max_html_bytes: int) -> object:
        del max_html_bytes
        raise SessionUnavailable("browser Session has no live driver")
