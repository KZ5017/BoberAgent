"""Core-owned durable transport inbox records; not World State."""

from boberagent_contracts import CapabilityRunRef, DomainRef, JsonObject
from boberagent_transport import DeliveryKind, TransportMessageId
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class TransportInboxRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: TransportMessageId
    node_id: str
    message_kind: DeliveryKind
    correlation_id: CapabilityRunRef
    payload_id: DomainRef
    outbox_sequence: int = Field(ge=1)
    envelope: JsonObject
    received_at: AwareDatetime
    delivery_count: int = Field(ge=1)
