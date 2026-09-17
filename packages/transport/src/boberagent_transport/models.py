"""Versioned JSON envelopes for the transport-neutral protocol."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Self

from boberagent_contracts import (
    AssetRef,
    CapabilityDefinition,
    CapabilityInvocation,
    CapabilityResult,
    CapabilityRunRef,
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

TRANSPORT_PROTOCOL_VERSION = "1.0"

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
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class DeliveryKind(StrEnum):
    EVENT = "event"
    RESULT = "result"


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
    degraded_reasons: tuple[str, ...] = ()


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
