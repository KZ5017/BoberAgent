"""Versioned JSON envelopes for the transport-neutral protocol."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Self

from boberagent_contracts import (
    AssetRef,
    CapabilityDefinition,
    CapabilityId,
    CapabilityInvocation,
    CapabilityResult,
    CapabilityRunRef,
    CapabilityRunStatus,
    DomainRef,
    Event,
    EventRef,
    JsonObject,
    MissionRef,
)
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from .errors import MalformedMessage, UnsupportedProtocolVersion

TRANSPORT_PROTOCOL_VERSION = "1.2"

type NodeIdentifier = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]


class TransportMessageId(DomainRef):
    """Stable identity for one transport-delivered logical message."""


class TransportModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )


class DeliveryKind(StrEnum):
    EVENT = "event"
    RESULT = "result"


class AdvertisedCapabilityStatus(StrEnum):
    """Node-local provider status projected through the neutral handshake."""

    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class CapabilityStatusAdvertisement(TransportModel):
    capability_id: CapabilityId
    status: AdvertisedCapabilityStatus
    reason: str | None = Field(default=None, min_length=1, max_length=1024)


class MissionProjection(TransportModel):
    mission_ref: MissionRef
    name: str | None = Field(default=None, min_length=1, max_length=255)
    profile: str | None = Field(default=None, min_length=1, max_length=255)
    objectives: tuple[str, ...] = ()
    metadata: JsonObject = Field(default_factory=dict)


class AssetProjection(TransportModel):
    asset_ref: AssetRef
    primary_address: str = Field(min_length=1, max_length=255)
    addresses: tuple[str, ...] = ()
    metadata: JsonObject = Field(default_factory=dict)


class InvocationDelivery(TransportModel):
    """Contract invocation plus the bounded local authorization/read projection."""

    invocation: CapabilityInvocation
    mission: MissionProjection
    allowed_assets: tuple[AssetRef, ...] = ()
    allowed_addresses: tuple[str, ...] = ()
    assets: tuple[AssetProjection, ...] = ()

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if self.invocation.mission_ref != self.mission.mission_ref:
            raise ValueError("Mission projection does not match CapabilityInvocation")
        refs = [asset.asset_ref for asset in self.assets]
        if len(refs) != len(set(refs)):
            raise ValueError("Asset projections must have unique references")
        return self


class InvocationEnvelope(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["capability.invocation"] = "capability.invocation"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    correlation_id: CapabilityRunRef
    timestamp: AwareDatetime
    delivery: InvocationDelivery

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.correlation_id != self.delivery.invocation.run_id:
            raise ValueError("Invocation correlation does not match CapabilityRunRef")
        if self.message_id != invocation_message_id(self.correlation_id):
            raise ValueError("Invocation message ID is not stable for its CapabilityRunRef")
        return self


class EventEnvelope(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["event"] = "event"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    correlation_id: CapabilityRunRef
    timestamp: AwareDatetime
    outbox_sequence: int = Field(ge=1)
    event: Event

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.message_id != event_message_id(self.event.event_id):
            raise ValueError("Event message ID is not stable for its EventRef")
        if str(self.event.source_ref) != str(self.correlation_id):
            raise ValueError("Event source does not match Run correlation")
        return self


class ResultEnvelope(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["result"] = "result"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    correlation_id: CapabilityRunRef
    timestamp: AwareDatetime
    outbox_sequence: int = Field(ge=1)
    result: CapabilityResult

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.correlation_id != self.result.run_ref:
            raise ValueError("Result correlation does not match CapabilityRunRef")
        if self.message_id != result_message_id(self.result.run_ref):
            raise ValueError("Result message ID is not stable for its CapabilityRunRef")
        return self


type OutboundEnvelope = Annotated[
    EventEnvelope | ResultEnvelope,
    Field(discriminator="message_type"),
]


class DeliveryAcknowledgement(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["delivery.acknowledgement"] = "delivery.acknowledgement"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    delivery_kind: DeliveryKind
    payload_id: DomainRef
    correlation_id: CapabilityRunRef
    acknowledged_at: AwareDatetime


class HandshakeRequest(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["node.handshake.request"] = "node.handshake.request"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    timestamp: AwareDatetime


class NodeAdvertisement(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["node.handshake.response"] = "node.handshake.response"
    request_message_id: TransportMessageId
    node_id: NodeIdentifier
    timestamp: AwareDatetime
    lifecycle: str
    database_ready: bool
    capabilities: tuple[CapabilityDefinition, ...]
    capability_statuses: tuple[CapabilityStatusAdvertisement, ...]
    degraded_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_capability_metadata(self) -> Self:
        capability_ids = [definition.capability_id for definition in self.capabilities]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("Node advertisement contains duplicate capability definitions")
        status_ids = [status.capability_id for status in self.capability_statuses]
        if len(status_ids) != len(set(status_ids)):
            raise ValueError("Node advertisement contains duplicate capability statuses")
        if set(status_ids) != set(capability_ids):
            raise ValueError("capability statuses must correspond exactly to definitions")
        return self


class RunStatusRequest(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["capability.run.status.request"] = "capability.run.status.request"
    message_id: TransportMessageId
    node_id: NodeIdentifier
    correlation_id: CapabilityRunRef
    timestamp: AwareDatetime


class RunStatusResponse(TransportModel):
    protocol_version: str = TRANSPORT_PROTOCOL_VERSION
    message_type: Literal["capability.run.status.response"] = "capability.run.status.response"
    request_message_id: TransportMessageId
    node_id: NodeIdentifier
    correlation_id: CapabilityRunRef
    status: CapabilityRunStatus | None


class TransportFailure(TransportModel):
    code: str
    message: str
    node_id: str | None = None
    message_id: str | None = None
    correlation_id: CapabilityRunRef | None = None


_outbound_adapter: TypeAdapter[OutboundEnvelope] = TypeAdapter(OutboundEnvelope)


def invocation_message_id(run_ref: CapabilityRunRef) -> TransportMessageId:
    return TransportMessageId(f"transport-invocation:{run_ref}")


def event_message_id(event_ref: EventRef) -> TransportMessageId:
    return TransportMessageId(f"transport-event:{event_ref}")


def result_message_id(run_ref: CapabilityRunRef) -> TransportMessageId:
    return TransportMessageId(f"transport-result:{run_ref}")


def ensure_supported_protocol(version: str) -> None:
    if version != TRANSPORT_PROTOCOL_VERSION:
        raise UnsupportedProtocolVersion(f"unsupported transport protocol version: {version}")


def serialize_message(message: TransportModel) -> bytes:
    return message.model_dump_json().encode("utf-8")


def parse_invocation(data: bytes) -> InvocationEnvelope:
    return _parse(InvocationEnvelope, data)


def parse_acknowledgement(data: bytes) -> DeliveryAcknowledgement:
    return _parse(DeliveryAcknowledgement, data)


def parse_handshake_request(data: bytes) -> HandshakeRequest:
    return _parse(HandshakeRequest, data)


def parse_advertisement(data: bytes) -> NodeAdvertisement:
    return _parse(NodeAdvertisement, data)


def parse_run_status_request(data: bytes) -> RunStatusRequest:
    return _parse(RunStatusRequest, data)


def parse_run_status_response(data: bytes) -> RunStatusResponse:
    return _parse(RunStatusResponse, data)


def parse_outbound(data: bytes) -> OutboundEnvelope:
    try:
        return _outbound_adapter.validate_json(data)
    except (ValidationError, ValueError, TypeError) as error:
        raise MalformedMessage("invalid outbound transport envelope") from error


def invocation_fingerprint(delivery: InvocationDelivery) -> str:
    canonical = json.dumps(
        delivery.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _parse[ModelT: TransportModel](model: type[ModelT], data: bytes) -> ModelT:
    try:
        return model.model_validate_json(data)
    except (ValidationError, ValueError, TypeError) as error:
        raise MalformedMessage(f"invalid {model.__name__} transport envelope") from error
