"""Node-owned TCP Listener Resource and incoming byte-stream Session runtime."""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
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
    ByteStreamRead,
    ExecutionTimeout,
    ResourceLease,
    ResourceUnavailable,
    SessionHandle,
    SessionLease,
    SessionUnavailable,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from boberagent_execution_node.events import EventOutbox, NodeEventService
from boberagent_execution_node.persistence import (
    ResourceRuntimeRecord,
    ResourceRuntimeState,
    RuntimeStore,
    SessionRuntimeRecord,
    SessionRuntimeState,
)

LISTENER_RESOURCE_TYPE = "tcp_listener"
STREAM_SESSION_TYPE = "tcp_stream"
LISTENER_PROVIDER = "asyncio.tcp"
MAX_STREAM_BYTES = 64 * 1024
MAX_LISTENER_SESSIONS = 32


def normalize_ip_address(value: str) -> str:
    """Return a canonical IP literal; listeners never bind implicit hostnames."""

    try:
        return ipaddress.ip_address(value).compressed
    except ValueError as error:
        raise ValueError("address must be an explicit IPv4 or IPv6 literal") from error


class ListenerResourceConfiguration(BaseModel):
    """Defensive Node-side validation for one bounded TCP listener."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bind_address: str
    port: int = Field(ge=0, le=65535)
    allowed_remote_addresses: tuple[str, ...] = Field(min_length=1, max_length=64)
    max_sessions: int = Field(default=8, ge=1, le=MAX_LISTENER_SESSIONS)

    @field_validator("bind_address")
    @classmethod
    def validate_bind_address(cls, value: str) -> str:
        normalized = normalize_ip_address(value)
        if ipaddress.ip_address(normalized).is_unspecified:
            raise ValueError("wildcard listener binds are not permitted by the M14 provider")
        return normalized

    @field_validator("allowed_remote_addresses")
    @classmethod
    def validate_remote_addresses(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(normalize_ip_address(value) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed remote addresses must be unique")
        return normalized


@dataclass(slots=True)
class _ListenerRuntime:
    server: asyncio.Server
    allowed_remote_addresses: frozenset[str]
    max_sessions: int


class ManagedTcpStreamSession:
    """Semantic bounded stream driver retaining socket internals inside the Node."""

    def __init__(
        self,
        *,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        touch: Callable[[], None],
        disconnected: Callable[[str], None],
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._touch = touch
        self._disconnected = disconnected
        self._closed = False

    @property
    def supported_operations(self) -> tuple[str, ...]:
        return ("receive", "send")

    async def receive(self, *, max_bytes: int, timeout: float) -> ByteStreamRead:
        self._require_open()
        if max_bytes < 1 or max_bytes > MAX_STREAM_BYTES:
            raise ValueError(f"receive bound must be between 1 and {MAX_STREAM_BYTES} bytes")
        if timeout <= 0:
            raise ValueError("receive timeout must be positive")
        try:
            data = await asyncio.wait_for(self._reader.read(max_bytes), timeout=timeout)
        except TimeoutError as error:
            raise ExecutionTimeout("TCP Session receive timed out") from error
        except (ConnectionError, OSError) as error:
            self._mark_disconnected("receive_failed")
            raise SessionUnavailable("TCP Session receive failed") from error
        if not data:
            self._mark_disconnected("peer_closed")
            return ByteStreamRead(data=b"", eof=True)
        self._touch()
        return ByteStreamRead(data=data)

    async def send(self, data: bytes, *, timeout: float) -> int:
        self._require_open()
        if not data or len(data) > MAX_STREAM_BYTES:
            raise ValueError(f"send payload must contain between 1 and {MAX_STREAM_BYTES} bytes")
        if timeout <= 0:
            raise ValueError("send timeout must be positive")
        try:
            self._writer.write(data)
            await asyncio.wait_for(self._writer.drain(), timeout=timeout)
        except TimeoutError as error:
            raise ExecutionTimeout("TCP Session send timed out") from error
        except (ConnectionError, OSError) as error:
            self._mark_disconnected("send_failed")
            raise SessionUnavailable("TCP Session send failed") from error
        self._touch()
        return len(data)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._writer.close()
        with suppress(ConnectionError, OSError):
            await self._writer.wait_closed()

    def _mark_disconnected(self, reason: str) -> None:
        if not self._closed:
            self._closed = True
            self._writer.close()
            self._disconnected(reason)

    def _require_open(self) -> None:
        if self._closed:
            raise SessionUnavailable("TCP Session is closed")


class ListenerRuntimeManager:
    """Own listener sockets, accept tasks, incoming streams, and durable lifecycle metadata."""

    def __init__(
        self,
        *,
        store: RuntimeStore,
        event_outbox: EventOutbox,
        clock: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._event_outbox = event_outbox
        self._clock = clock
        self._listeners: dict[str, _ListenerRuntime] = {}
        self._sessions: dict[str, ManagedTcpStreamSession] = {}
        self._resource_locks: dict[str, asyncio.Lock] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._accept_tasks: dict[str, set[asyncio.Task[None]]] = {}

    @property
    def active_listener_count(self) -> int:
        return len(self._listeners)

    @property
    def active_session_count(self) -> int:
        return len(self._sessions)

    @property
    def active_accept_task_count(self) -> int:
        return sum(len(tasks) for tasks in self._accept_tasks.values())

    def resource_service(self, run_ref: CapabilityRunRef) -> ListenerResourceService:
        return ListenerResourceService(self, run_ref)

    def session_service(self, run_ref: CapabilityRunRef) -> ListenerSessionService:
        return ListenerSessionService(self, run_ref)

    async def create_resource(
        self,
        *,
        run_ref: CapabilityRunRef,
        resource_type: str,
        configuration: JsonObject,
        owner_ref: DomainRef | None,
    ) -> ResourceDescriptor:
        if resource_type != LISTENER_RESOURCE_TYPE:
            raise ResourceUnavailable(f"unsupported Resource type: {resource_type}")
        effective_owner = owner_ref or run_ref
        if str(effective_owner) not in self._allowed_owners(run_ref):
            raise ResourceUnavailable("Resource owner is outside the current invocation provenance")
        try:
            parsed = ListenerResourceConfiguration.model_validate(configuration)
        except ValidationError as error:
            raise ResourceUnavailable("invalid TCP Listener Resource configuration") from error

        now = self._clock()
        resource_ref = ResourceRef(f"resource-listener-{uuid4()}")
        metadata: JsonObject = {
            "protocol": "tcp",
            "bind_address": parsed.bind_address,
            "requested_port": parsed.port,
            "bound_address": None,
            "bound_port": None,
            "allowed_remote_addresses": list(parsed.allowed_remote_addresses),
            "max_sessions": parsed.max_sessions,
            "active_sessions": 0,
            "accepted_sessions": 0,
            "last_activity_at": now.isoformat(),
        }
        descriptor = ResourceDescriptor(
            resource_id=resource_ref,
            resource_type=LISTENER_RESOURCE_TYPE,
            provider=LISTENER_PROVIDER,
            state=ResourceRuntimeState.CREATING.value,
            owner_ref=effective_owner,
            created_by_run=run_ref,
            created_at=now,
            access_modes=(AccessMode.EXCLUSIVE,),
            lifecycle_metadata=metadata,
        )
        self._store.add_resource(
            ResourceRuntimeRecord(
                descriptor=descriptor,
                updated_at=now,
                last_activity_at=now,
            )
        )
        try:
            self._ensure_managed_endpoint_available(parsed.bind_address, parsed.port, resource_ref)
            server = await asyncio.start_server(
                lambda reader, writer: self._schedule_accept(resource_ref, reader, writer),
                host=parsed.bind_address,
                port=parsed.port,
                limit=MAX_STREAM_BYTES * 2,
                backlog=parsed.max_sessions,
                start_serving=False,
            )
            bound_address, bound_port = _server_endpoint(server)
            runtime = _ListenerRuntime(
                server=server,
                allowed_remote_addresses=frozenset(parsed.allowed_remote_addresses),
                max_sessions=parsed.max_sessions,
            )
            self._listeners[str(resource_ref)] = runtime
            metadata = {
                **metadata,
                "bound_address": bound_address,
                "bound_port": bound_port,
                "last_activity_at": self._clock().isoformat(),
            }
            await server.start_serving()
        except Exception as error:
            key = str(resource_ref)
            failed_runtime = self._listeners.pop(key) if key in self._listeners else None
            if failed_runtime is not None:
                failed_runtime.server.close()
                await failed_runtime.server.wait_closed()
            self._store.update_resource_state(
                resource_ref,
                ResourceRuntimeState.FAILED,
                self._clock(),
                lifecycle_metadata=metadata,
            )
            raise ResourceUnavailable("TCP Listener Resource failed to bind") from error

        self._store.update_resource_state(
            resource_ref,
            ResourceRuntimeState.READY,
            self._clock(),
            lifecycle_metadata=metadata,
        )
        return self.get_resource(resource_ref)

    def get_resource(self, resource_ref: ResourceRef) -> ResourceDescriptor:
        return self._require_resource(resource_ref).descriptor

    def acquire_resource(self, resource_ref: ResourceRef, mode: AccessMode) -> ResourceLease:
        descriptor = self.get_resource(resource_ref)
        if mode not in descriptor.access_modes:
            raise ResourceUnavailable(f"Resource does not support {mode}: {resource_ref}")
        return _ListenerResourceLease(self, resource_ref, mode)

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
            runtime = self._listeners.pop(str(resource_ref), None)
            if runtime is not None:
                runtime.server.close()
            await self._stop_accept_tasks(resource_ref)
            for session in self._store.list_sessions_for_resource(resource_ref):
                await self.close_session(session.descriptor.session_id, reason="listener_closed")
            if runtime is not None:
                await runtime.server.wait_closed()
            self._store.update_resource_state(
                resource_ref, ResourceRuntimeState.CLOSED, self._clock()
            )

    def get_session(self, session_ref: SessionRef) -> SessionHandle:
        record = self._require_session(session_ref)
        driver = self._sessions.get(str(session_ref), _UnavailableByteStreamDriver())
        return SessionHandle(record.descriptor, driver)

    def acquire_session(self, session_ref: SessionRef, mode: AccessMode) -> SessionLease:
        record = self._require_session(session_ref)
        if mode not in record.descriptor.access_modes:
            raise SessionUnavailable(f"Session does not support {mode}: {session_ref}")
        if SessionRuntimeState(record.descriptor.state) is not SessionRuntimeState.ACTIVE:
            raise SessionUnavailable(f"Session is not active: {session_ref}")
        self._require_live_backing_listener(record)
        if str(session_ref) not in self._sessions:
            raise SessionUnavailable(f"Session has no live TCP stream: {session_ref}")
        return _ListenerSessionLease(self, session_ref, mode)

    async def close_session(self, session_ref: SessionRef, *, reason: str = "requested") -> None:
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
            if driver is not None:
                await driver.close()
            self._store.update_session_state(session_ref, SessionRuntimeState.CLOSED, self._clock())
            self._update_listener_counts(record.descriptor.resource_refs[0])
            self._emit_session_event("session.closed", record.descriptor, {"reason": reason})

    async def shutdown(self) -> None:
        for resource_ref in tuple(ResourceRef(value) for value in self._listeners):
            await self.close_resource(resource_ref)
        for tasks in tuple(self._accept_tasks.values()):
            for task in tasks:
                task.cancel()
        remaining = tuple(task for tasks in self._accept_tasks.values() for task in tasks)
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)
        self._accept_tasks.clear()

    def assert_resource_access(self, resource_ref: ResourceRef, run_ref: CapabilityRunRef) -> None:
        descriptor = self._require_resource(resource_ref).descriptor
        if str(descriptor.owner_ref) not in self._allowed_owners(run_ref):
            raise ResourceUnavailable("Resource is not owned by this invocation provenance")

    def assert_session_access(self, session_ref: SessionRef, run_ref: CapabilityRunRef) -> None:
        descriptor = self._require_session(session_ref).descriptor
        if str(descriptor.owner_ref) not in self._allowed_owners(run_ref):
            raise SessionUnavailable("Session is not owned by this invocation provenance")

    def _schedule_accept(
        self,
        resource_ref: ResourceRef,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.create_task(
            self._accept_connection(resource_ref, reader, writer),
            name=f"boberagent-listener-accept:{resource_ref}",
        )
        tasks = self._accept_tasks.setdefault(str(resource_ref), set())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def _accept_connection(
        self,
        resource_ref: ResourceRef,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        accepted = False
        try:
            runtime = self._listeners.get(str(resource_ref))
            resource = self._require_resource(resource_ref)
            if (
                runtime is None
                or ResourceRuntimeState(resource.descriptor.state) is not ResourceRuntimeState.READY
            ):
                return
            remote_address, remote_port = _stream_endpoint(writer.get_extra_info("peername"))
            local_address, local_port = _stream_endpoint(writer.get_extra_info("sockname"))
            if remote_address not in runtime.allowed_remote_addresses:
                self._emit_rejection(
                    resource.descriptor,
                    reason="remote_not_authorized",
                    remote_address=remote_address,
                    remote_port=remote_port,
                )
                return
            if self._active_sessions_for(resource_ref) >= runtime.max_sessions:
                self._emit_rejection(
                    resource.descriptor,
                    reason="capacity_reached",
                    remote_address=remote_address,
                    remote_port=remote_port,
                )
                return

            now = self._clock()
            session_ref = SessionRef(f"session-tcp-{uuid4()}")
            descriptor = SessionDescriptor(
                session_id=session_ref,
                session_type=STREAM_SESSION_TYPE,
                state=SessionRuntimeState.ACTIVE.value,
                provider=LISTENER_PROVIDER,
                owner_ref=resource.descriptor.owner_ref,
                created_by_run=resource.descriptor.created_by_run,
                created_at=now,
                resource_refs=(resource_ref,),
                supported_operations=("receive", "send"),
                access_modes=(AccessMode.EXCLUSIVE,),
                lifecycle_metadata={
                    "remote_address": remote_address,
                    "remote_port": remote_port,
                    "local_address": local_address,
                    "local_port": local_port,
                    "accepted_at": now.isoformat(),
                    "last_activity_at": now.isoformat(),
                },
            )
            self._store.add_session(
                SessionRuntimeRecord(
                    descriptor=descriptor,
                    updated_at=now,
                    last_activity_at=now,
                )
            )
            driver = ManagedTcpStreamSession(
                reader=reader,
                writer=writer,
                touch=lambda: self._touch_stream(session_ref, resource_ref),
                disconnected=lambda reason: self._mark_stream_disconnected(
                    session_ref, resource_ref, reason
                ),
            )
            self._sessions[str(session_ref)] = driver
            accepted = True
            self._update_listener_counts(resource_ref)
            self._emit_session_event("session.created", descriptor, {})
        except asyncio.CancelledError:
            raise
        except Exception:
            rejected_resource = self._store.get_resource(resource_ref)
            if rejected_resource is not None:
                self._emit_rejection(
                    rejected_resource.descriptor,
                    reason="accept_failed",
                    remote_address=None,
                    remote_port=None,
                )
        finally:
            if not accepted:
                writer.close()
                with suppress(ConnectionError, OSError):
                    await writer.wait_closed()

    def _touch_stream(self, session_ref: SessionRef, resource_ref: ResourceRef) -> None:
        now = self._clock()
        self._store.touch_session(session_ref, now)
        self._store.touch_resource(resource_ref, now)

    def _mark_stream_disconnected(
        self, session_ref: SessionRef, resource_ref: ResourceRef, reason: str
    ) -> None:
        record = self._store.get_session(session_ref)
        if record is None or SessionRuntimeState(record.descriptor.state) in {
            SessionRuntimeState.CLOSED,
            SessionRuntimeState.LOST,
        }:
            return
        self._sessions.pop(str(session_ref), None)
        self._store.update_session_state(session_ref, SessionRuntimeState.CLOSED, self._clock())
        self._update_listener_counts(resource_ref)
        self._emit_session_event("session.closed", record.descriptor, {"reason": reason})

    def _emit_session_event(
        self, event_type: str, descriptor: SessionDescriptor, extra: JsonObject
    ) -> None:
        metadata = descriptor.lifecycle_metadata
        payload: JsonObject = {
            "session_ref": str(descriptor.session_id),
            "resource_ref": str(descriptor.resource_refs[0]),
            "session_type": descriptor.session_type,
            "remote_address": metadata.get("remote_address"),
            "remote_port": metadata.get("remote_port"),
            "local_address": metadata.get("local_address"),
            "local_port": metadata.get("local_port"),
            "accepted_at": metadata.get("accepted_at"),
            "owner_ref": str(descriptor.owner_ref),
            **extra,
        }
        self._events_for_run(descriptor.created_by_run).runtime_event(event_type, payload)

    def _emit_rejection(
        self,
        descriptor: ResourceDescriptor,
        *,
        reason: str,
        remote_address: str | None,
        remote_port: int | None,
    ) -> None:
        self._events_for_run(descriptor.created_by_run).runtime_event(
            "session.rejected",
            {
                "resource_ref": str(descriptor.resource_id),
                "session_type": STREAM_SESSION_TYPE,
                "reason": reason,
                "remote_address": remote_address,
                "remote_port": remote_port,
                "owner_ref": str(descriptor.owner_ref),
            },
        )

    def _events_for_run(self, run_ref: CapabilityRunRef) -> NodeEventService:
        run = self._store.get_run(run_ref)
        if run is None:
            raise RuntimeError(f"unknown listener-creating Run: {run_ref}")
        return NodeEventService(
            outbox=self._event_outbox,
            mission_ref=run.mission_ref,
            run_ref=run_ref,
            clock=self._clock,
        )

    def _update_listener_counts(self, resource_ref: ResourceRef) -> None:
        record = self._require_resource(resource_ref)
        sessions = self._store.list_sessions_for_resource(resource_ref)
        metadata: JsonObject = {
            **record.descriptor.lifecycle_metadata,
            "active_sessions": sum(
                session.descriptor.state == SessionRuntimeState.ACTIVE.value for session in sessions
            ),
            "accepted_sessions": len(sessions),
            "last_activity_at": self._clock().isoformat(),
        }
        self._store.update_resource_state(
            resource_ref,
            ResourceRuntimeState(record.descriptor.state),
            self._clock(),
            lifecycle_metadata=metadata,
        )

    def _ensure_managed_endpoint_available(
        self, bind_address: str, port: int, resource_ref: ResourceRef
    ) -> None:
        if port == 0:
            return
        for record in self._store.list_resources():
            descriptor = record.descriptor
            metadata = descriptor.lifecycle_metadata
            if (
                descriptor.resource_id != resource_ref
                and descriptor.resource_type == LISTENER_RESOURCE_TYPE
                and descriptor.state == ResourceRuntimeState.READY.value
                and metadata.get("bound_address") == bind_address
                and metadata.get("bound_port") == port
            ):
                raise ResourceUnavailable("managed TCP listener endpoint is already in use")

    def _active_sessions_for(self, resource_ref: ResourceRef) -> int:
        return sum(
            record.descriptor.resource_refs == (resource_ref,)
            and record.descriptor.state == SessionRuntimeState.ACTIVE.value
            for record in self._store.list_sessions_for_resource(resource_ref)
        )

    def _require_resource(self, resource_ref: ResourceRef) -> ResourceRuntimeRecord:
        record = self._store.get_resource(resource_ref)
        if record is None:
            raise ResourceUnavailable(f"unknown Resource: {resource_ref}")
        if record.descriptor.resource_type != LISTENER_RESOURCE_TYPE:
            raise ResourceUnavailable(f"Resource is not a TCP listener: {resource_ref}")
        return record

    def _require_session(self, session_ref: SessionRef) -> SessionRuntimeRecord:
        record = self._store.get_session(session_ref)
        if record is None:
            raise SessionUnavailable(f"unknown Session: {session_ref}")
        if record.descriptor.session_type != STREAM_SESSION_TYPE:
            raise SessionUnavailable(f"Session is not a TCP stream: {session_ref}")
        return record

    def _require_live_backing_listener(self, record: SessionRuntimeRecord) -> ResourceRef:
        if len(record.descriptor.resource_refs) != 1:
            raise SessionUnavailable("TCP Session has invalid Listener ownership metadata")
        resource_ref = record.descriptor.resource_refs[0]
        try:
            resource = self._require_resource(resource_ref)
        except ResourceUnavailable as error:
            raise SessionUnavailable("backing Listener Resource is unavailable") from error
        if ResourceRuntimeState(resource.descriptor.state) is not ResourceRuntimeState.READY:
            raise SessionUnavailable("backing Listener Resource is not ready")
        if str(resource_ref) not in self._listeners:
            raise SessionUnavailable("backing Listener Resource has no live socket")
        return resource_ref

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
            descriptor = self.get_resource(resource_ref)
            if ResourceRuntimeState(descriptor.state) is not ResourceRuntimeState.READY:
                raise ResourceUnavailable(f"Resource is not ready: {resource_ref}")
            if str(resource_ref) not in self._listeners:
                raise ResourceUnavailable(f"Resource has no live listener: {resource_ref}")
            return descriptor
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
            self._require_live_backing_listener(record)
            driver = self._sessions.get(str(session_ref))
            if driver is None:
                raise SessionUnavailable(f"Session has no live TCP stream: {session_ref}")
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

    async def _stop_accept_tasks(self, resource_ref: ResourceRef) -> None:
        tasks = tuple(self._accept_tasks.pop(str(resource_ref), set()))
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class ListenerResourceService:
    def __init__(self, manager: ListenerRuntimeManager, run_ref: CapabilityRunRef) -> None:
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


class ListenerSessionService:
    def __init__(self, manager: ListenerRuntimeManager, run_ref: CapabilityRunRef) -> None:
        self._manager = manager
        self._run_ref = run_ref

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


class _ListenerResourceLease:
    def __init__(
        self,
        manager: ListenerRuntimeManager,
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


class _ListenerSessionLease:
    def __init__(
        self,
        manager: ListenerRuntimeManager,
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


class _UnavailableByteStreamDriver:
    @property
    def supported_operations(self) -> tuple[str, ...]:
        return ("receive", "send")

    async def receive(self, *, max_bytes: int, timeout: float) -> ByteStreamRead:
        del max_bytes, timeout
        raise SessionUnavailable("TCP Session has no live stream")

    async def send(self, data: bytes, *, timeout: float) -> int:
        del data, timeout
        raise SessionUnavailable("TCP Session has no live stream")


def _server_endpoint(server: asyncio.Server) -> tuple[str, int]:
    sockets = server.sockets
    if not sockets:
        raise RuntimeError("TCP listener did not expose a bound socket")
    return _stream_endpoint(sockets[0].getsockname())


def _stream_endpoint(value: object) -> tuple[str, int]:
    if not isinstance(value, tuple) or len(value) < 2:
        raise RuntimeError("TCP stream did not expose a valid endpoint")
    address, port = value[0], value[1]
    if not isinstance(address, str) or not isinstance(port, int):
        raise RuntimeError("TCP stream endpoint has invalid address metadata")
    return normalize_ip_address(address), port
