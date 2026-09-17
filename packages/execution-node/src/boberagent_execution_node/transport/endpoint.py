"""Serialized protocol adapter delegating execution to CapabilityRuntime."""

from __future__ import annotations

import asyncio

from boberagent_contracts import (
    CapabilityInvocation,
    CapabilityResult,
    CapabilityRunRef,
    EventRef,
)
from boberagent_sdk import AssetSnapshot, MissionContext
from boberagent_transport import (
    AdvertisedCapabilityStatus,
    CapabilityStatusAdvertisement,
    ConflictingInvocation,
    DeliveryKind,
    EventEnvelope,
    NodeAdvertisement,
    ProtocolError,
    ResultEnvelope,
    ensure_supported_protocol,
    event_message_id,
    invocation_fingerprint,
    parse_acknowledgement,
    parse_handshake_request,
    parse_invocation,
    result_message_id,
    serialize_message,
)

from boberagent_execution_node.node import ExecutionNode
from boberagent_execution_node.persistence import RuntimeStore
from boberagent_execution_node.services import LocalInvocationEnvironment


class ExecutionNodeTransportEndpoint:
    """Translate protocol envelopes without duplicating Capability Runtime behavior."""

    def __init__(self, node: ExecutionNode) -> None:
        if node.identity is None or node.store is None:
            raise RuntimeError("Execution Node must be initialized before transport registration")
        self._node = node
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def node_id(self) -> str:
        identity = self._node.identity
        if identity is None:
            raise RuntimeError("Execution Node identity is unavailable")
        return str(identity.node_id)

    async def handshake(self, request: bytes) -> bytes:
        envelope = parse_handshake_request(request)
        ensure_supported_protocol(envelope.protocol_version)
        if envelope.node_id != self.node_id:
            raise ProtocolError("handshake targeted a different Node", node_id=self.node_id)
        health = self._node.health()
        providers = tuple(
            provider
            for provider in self._node.capabilities.providers()
            if provider.availability.value != "DISABLED"
        )
        response = NodeAdvertisement(
            request_message_id=envelope.message_id,
            node_id=self.node_id,
            timestamp=health.checked_at,
            lifecycle=health.lifecycle.value,
            database_ready=health.database_ready,
            capabilities=tuple(provider.definition for provider in providers),
            capability_statuses=tuple(
                CapabilityStatusAdvertisement(
                    capability_id=provider.definition.capability_id,
                    status=AdvertisedCapabilityStatus(provider.availability.value),
                    reason=provider.failure or provider.availability_reason,
                )
                for provider in providers
            ),
            degraded_reasons=health.degraded_reasons,
        )
        return serialize_message(response)

    async def accept_invocation(self, message: bytes) -> None:
        envelope = parse_invocation(message)
        ensure_supported_protocol(envelope.protocol_version)
        if envelope.node_id != self.node_id:
            raise ProtocolError(
                "invocation targeted a different Node",
                node_id=self.node_id,
                message_id=str(envelope.message_id),
                correlation_id=envelope.correlation_id,
            )
        fingerprint = invocation_fingerprint(envelope.delivery)
        lock = self._locks.setdefault(str(envelope.correlation_id), asyncio.Lock())
        async with lock:
            store = self._require_store()
            existing = store.get_run(envelope.correlation_id)
            if existing is not None:
                self._validate_duplicate(envelope.delivery.invocation, fingerprint)
                return
            environment = LocalInvocationEnvironment(
                mission=MissionContext(
                    mission_ref=envelope.delivery.mission.mission_ref,
                    name=envelope.delivery.mission.name,
                    profile=envelope.delivery.mission.profile,
                    objectives=envelope.delivery.mission.objectives,
                    metadata=envelope.delivery.mission.metadata,
                ),
                allowed_assets=frozenset(envelope.delivery.allowed_assets),
                allowed_addresses=frozenset(envelope.delivery.allowed_addresses),
                entities=tuple(
                    AssetSnapshot(
                        ref=asset.asset_ref,
                        primary_address=asset.primary_address,
                        addresses=asset.addresses,
                        metadata=asset.metadata,
                    )
                    for asset in envelope.delivery.assets
                ),
            )
            await self._node.execute_local(
                envelope.delivery.invocation,
                environment,
                invocation_fingerprint=fingerprint,
            )

    async def pending_outbound(self) -> tuple[bytes, ...]:
        store = self._require_store()
        messages: list[bytes] = []
        for event_record in store.pending_events():
            correlation_id = CapabilityRunRef(str(event_record.event.source_ref))
            messages.append(
                serialize_message(
                    EventEnvelope(
                        message_id=event_message_id(event_record.event.event_id),
                        node_id=self.node_id,
                        correlation_id=correlation_id,
                        timestamp=event_record.created_at,
                        outbox_sequence=event_record.sequence,
                        event=event_record.event,
                    )
                )
            )
        for result_record in store.pending_results():
            result = CapabilityResult.model_validate(result_record.result_json)
            messages.append(
                serialize_message(
                    ResultEnvelope(
                        message_id=result_message_id(result_record.run_ref),
                        node_id=self.node_id,
                        correlation_id=result_record.run_ref,
                        timestamp=result_record.created_at,
                        outbox_sequence=result_record.sequence,
                        result=result,
                    )
                )
            )
        return tuple(messages)

    async def acknowledge(self, message: bytes) -> None:
        acknowledgement = parse_acknowledgement(message)
        ensure_supported_protocol(acknowledgement.protocol_version)
        if acknowledgement.node_id != self.node_id:
            raise ProtocolError("acknowledgement targeted a different Node")
        store = self._require_store()
        try:
            if acknowledgement.delivery_kind is DeliveryKind.EVENT:
                event_ref = EventRef(str(acknowledgement.payload_id))
                if acknowledgement.message_id != event_message_id(event_ref):
                    raise ProtocolError("Event acknowledgement identity mismatch")
                store.acknowledge_event(event_ref, acknowledgement.correlation_id)
            else:
                run_ref = CapabilityRunRef(str(acknowledgement.payload_id))
                if acknowledgement.message_id != result_message_id(run_ref):
                    raise ProtocolError("Result acknowledgement identity mismatch")
                store.acknowledge_result(run_ref, acknowledgement.correlation_id)
        except (KeyError, ValueError) as error:
            raise ProtocolError("acknowledgement does not match a Node outbox record") from error

    def _validate_duplicate(self, invocation: CapabilityInvocation, fingerprint: str) -> None:
        record = self._require_store().get_run(invocation.run_id)
        if record is None:
            raise RuntimeError("duplicate Run disappeared during validation")
        same_stored_identity = (
            record.mission_ref == invocation.mission_ref
            and record.capability_id == invocation.capability_id
            and record.operation == invocation.operation
            and record.parent_run_ref == invocation.parent_run_ref
            and record.workflow_run_ref == invocation.workflow_run_ref
        )
        if (
            not same_stored_identity
            or record.invocation_fingerprint is None
            or record.invocation_fingerprint != fingerprint
        ):
            raise ConflictingInvocation(
                "CapabilityRunRef was reused with different invocation content",
                node_id=self.node_id,
                correlation_id=invocation.run_id,
            )

    def _require_store(self) -> RuntimeStore:
        store = self._node.store
        if not isinstance(store, RuntimeStore):
            raise RuntimeError("Execution Node runtime store is unavailable")
        return store
