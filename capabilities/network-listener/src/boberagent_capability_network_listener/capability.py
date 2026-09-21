"""Production ``network.listener`` capability orchestration."""

from __future__ import annotations

import base64

from boberagent_contracts import (
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRunStatus,
    JsonObject,
    ResourceDescriptor,
    ResourceRef,
    SessionDescriptor,
    SessionRef,
)
from boberagent_sdk import (
    ByteStreamSession,
    Capability,
    ExecutionContext,
    InputError,
    ResourceUnavailable,
    SessionHandle,
    SessionUnavailable,
)
from pydantic import BaseModel

from .inputs import (
    CloseListenerInput,
    CloseSessionInput,
    InspectListenerInput,
    ListenerInput,
    OpenListenerInput,
    ReceiveInput,
    SendInput,
)

_RESOURCE_TYPE = "tcp_listener"
_SESSION_TYPE = "tcp_stream"


class NetworkListenerCapability(Capability):
    capability_id = "network.listener"

    async def execute(
        self,
        operation: str,
        ctx: ExecutionContext,
        inputs: BaseModel,
    ) -> CapabilityResult:
        if not isinstance(inputs, ListenerInput):
            raise InputError("network.listener requires a validated listener input model")
        await ctx.cancellation.checkpoint()
        if operation == "open" and isinstance(inputs, OpenListenerInput):
            return await self._open(ctx, inputs)
        if operation == "inspect" and isinstance(inputs, InspectListenerInput):
            return await self._inspect(ctx, inputs)
        if operation == "receive" and isinstance(inputs, ReceiveInput):
            return await self._receive(ctx, inputs)
        if operation == "send" and isinstance(inputs, SendInput):
            return await self._send(ctx, inputs)
        if operation == "close_session" and isinstance(inputs, CloseSessionInput):
            return await self._close_session(ctx, inputs)
        if operation == "close_listener" and isinstance(inputs, CloseListenerInput):
            return await self._close_listener(ctx, inputs)
        raise InputError(f"unsupported network.listener operation: {operation}")

    async def _open(self, ctx: ExecutionContext, inputs: OpenListenerInput) -> CapabilityResult:
        await ctx.scope.assert_address_allowed(inputs.bind_address)
        for address in inputs.allowed_remote_addresses:
            await ctx.scope.assert_address_allowed(address)
        resource = await ctx.resources.create(
            resource_type=_RESOURCE_TYPE,
            configuration={
                "bind_address": inputs.bind_address,
                "port": inputs.port,
                "allowed_remote_addresses": list(inputs.allowed_remote_addresses),
                "max_sessions": inputs.max_sessions,
            },
            owner_ref=ctx.mission.mission_ref,
        )
        return CapabilityResult(
            run_ref=ctx.invocation.run_id,
            execution_status=CapabilityRunStatus.COMPLETED,
            outcome=CapabilityOutcome(
                category=CapabilityOutcomeCategory.SUCCESS,
                code="LISTENER_OPENED",
                summary="A managed TCP Listener Resource is ready for authorized peers.",
                details=_resource_details(resource),
            ),
            resources=(resource,),
        )

    async def _inspect(
        self, ctx: ExecutionContext, inputs: InspectListenerInput
    ) -> CapabilityResult:
        resource = await self._validate_resource(ctx, inputs.resource_ref)
        return _success(
            ctx,
            code="LISTENER_INSPECTED",
            summary="Listener Resource metadata was inspected.",
            details=_resource_details(resource),
        )

    async def _receive(self, ctx: ExecutionContext, inputs: ReceiveInput) -> CapabilityResult:
        handle = await self._validate_session(ctx, inputs.session_ref)
        async with ctx.sessions.acquire(inputs.session_ref) as leased:
            driver = _byte_stream_driver(leased)
            received = await driver.receive(
                max_bytes=inputs.max_bytes,
                timeout=inputs.timeout_seconds,
            )
        return _success(
            ctx,
            code="STREAM_BYTES_RECEIVED",
            summary="Bounded bytes were received from the managed TCP Session.",
            details={
                **_session_details(handle.descriptor),
                "payload_base64": base64.b64encode(received.data).decode("ascii"),
                "bytes_received": len(received.data),
                "eof": received.eof,
            },
        )

    async def _send(self, ctx: ExecutionContext, inputs: SendInput) -> CapabilityResult:
        handle = await self._validate_session(ctx, inputs.session_ref)
        payload = inputs.payload_bytes()
        async with ctx.sessions.acquire(inputs.session_ref) as leased:
            sent = await _byte_stream_driver(leased).send(
                payload,
                timeout=inputs.timeout_seconds,
            )
        return _success(
            ctx,
            code="STREAM_BYTES_SENT",
            summary="Bounded bytes were written to the managed TCP Session.",
            details={**_session_details(handle.descriptor), "bytes_sent": sent},
        )

    async def _close_session(
        self, ctx: ExecutionContext, inputs: CloseSessionInput
    ) -> CapabilityResult:
        handle = await self._validate_session(ctx, inputs.session_ref, require_active=False)
        was_closed = handle.descriptor.state.upper() in {"CLOSED", "LOST"}
        await ctx.sessions.close(inputs.session_ref)
        current = await ctx.sessions.get(inputs.session_ref)
        return _success(
            ctx,
            code=("STREAM_SESSION_ALREADY_CLOSED" if was_closed else "STREAM_SESSION_CLOSED"),
            summary="The incoming TCP Session is closed.",
            details=_session_details(current.descriptor),
        )

    async def _close_listener(
        self, ctx: ExecutionContext, inputs: CloseListenerInput
    ) -> CapabilityResult:
        resource = await self._validate_resource(ctx, inputs.resource_ref)
        was_closed = resource.state.upper() in {"CLOSED", "LOST"}
        await ctx.resources.close(inputs.resource_ref)
        current = await ctx.resources.get(inputs.resource_ref)
        return _success(
            ctx,
            code=("LISTENER_ALREADY_CLOSED" if was_closed else "LISTENER_CLOSED"),
            summary="The Listener Resource and its dependent live Sessions are closed.",
            details=_resource_details(current),
        )

    async def _validate_resource(
        self, ctx: ExecutionContext, resource_ref: ResourceRef
    ) -> ResourceDescriptor:
        descriptor = await ctx.resources.get(resource_ref)
        if descriptor.resource_type != _RESOURCE_TYPE:
            raise ResourceUnavailable("requested Resource is not a TCP listener")
        if str(descriptor.owner_ref) != str(ctx.mission.mission_ref):
            raise ResourceUnavailable("Listener Resource does not belong to this Mission")
        return descriptor

    async def _validate_session(
        self,
        ctx: ExecutionContext,
        session_ref: SessionRef,
        *,
        require_active: bool = True,
    ) -> SessionHandle:
        handle = await ctx.sessions.get(session_ref)
        descriptor = handle.descriptor
        if descriptor.session_type != _SESSION_TYPE:
            raise SessionUnavailable("requested Session is not a TCP stream")
        if str(descriptor.owner_ref) != str(ctx.mission.mission_ref):
            raise SessionUnavailable("TCP Session does not belong to this Mission")
        if len(descriptor.resource_refs) != 1:
            raise SessionUnavailable("TCP Session has invalid Listener ownership metadata")
        if require_active and descriptor.state.upper() != "ACTIVE":
            raise SessionUnavailable("TCP Session is not active")
        remote_address = descriptor.lifecycle_metadata.get("remote_address")
        if not isinstance(remote_address, str):
            raise SessionUnavailable("TCP Session has invalid remote address metadata")
        await ctx.scope.assert_address_allowed(remote_address)
        return handle


def _byte_stream_driver(handle: SessionHandle) -> ByteStreamSession:
    if not isinstance(handle.driver, ByteStreamSession):
        raise SessionUnavailable("Session does not provide bounded byte-stream semantics")
    return handle.driver


def _resource_details(descriptor: ResourceDescriptor) -> JsonObject:
    return {
        "resource_ref": str(descriptor.resource_id),
        "resource_type": descriptor.resource_type,
        "state": descriptor.state,
        **descriptor.lifecycle_metadata,
    }


def _session_details(descriptor: SessionDescriptor) -> JsonObject:
    return {
        "session_ref": str(descriptor.session_id),
        "resource_ref": str(descriptor.resource_refs[0]),
        "session_type": descriptor.session_type,
        "state": descriptor.state,
        "remote_address": descriptor.lifecycle_metadata.get("remote_address"),
        "remote_port": descriptor.lifecycle_metadata.get("remote_port"),
        "local_address": descriptor.lifecycle_metadata.get("local_address"),
        "local_port": descriptor.lifecycle_metadata.get("local_port"),
    }


def _success(
    ctx: ExecutionContext,
    *,
    code: str,
    summary: str,
    details: JsonObject,
) -> CapabilityResult:
    return CapabilityResult(
        run_ref=ctx.invocation.run_id,
        execution_status=CapabilityRunStatus.COMPLETED,
        outcome=CapabilityOutcome(
            category=CapabilityOutcomeCategory.SUCCESS,
            code=code,
            summary=summary,
            details=details,
        ),
    )
