"""Validated semantic inputs for ``network.listener``."""

from __future__ import annotations

import base64
import binascii
import ipaddress

from boberagent_contracts import ResourceRef, SessionRef
from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_STREAM_BYTES = 64 * 1024
MAX_ENCODED_PAYLOAD_CHARS = ((MAX_STREAM_BYTES + 2) // 3) * 4


def _normalize_ip(value: str) -> str:
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError as error:
        raise ValueError("address must be an explicit IPv4 or IPv6 literal") from error


class ListenerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OpenListenerInput(ListenerInput):
    bind_address: str
    port: int = Field(default=0, ge=0, le=65535)
    allowed_remote_addresses: tuple[str, ...] = Field(min_length=1, max_length=64)
    max_sessions: int = Field(default=8, ge=1, le=32)

    @field_validator("bind_address")
    @classmethod
    def validate_bind_address(cls, value: str) -> str:
        normalized = _normalize_ip(value)
        if ipaddress.ip_address(normalized).is_unspecified:
            raise ValueError("wildcard bind addresses are not permitted")
        return normalized

    @field_validator("allowed_remote_addresses")
    @classmethod
    def validate_remote_addresses(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_normalize_ip(value) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed remote addresses must be unique")
        return normalized


class InspectListenerInput(ListenerInput):
    resource_ref: ResourceRef


class ReceiveInput(ListenerInput):
    session_ref: SessionRef
    max_bytes: int = Field(default=4096, ge=1, le=MAX_STREAM_BYTES)
    timeout_seconds: float = Field(default=5.0, gt=0, le=30.0)


class SendInput(ListenerInput):
    session_ref: SessionRef
    payload_base64: str = Field(min_length=4, max_length=MAX_ENCODED_PAYLOAD_CHARS)
    timeout_seconds: float = Field(default=5.0, gt=0, le=30.0)

    @field_validator("payload_base64")
    @classmethod
    def validate_payload(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("payload_base64 must be valid canonical base64") from error
        if not decoded or len(decoded) > MAX_STREAM_BYTES:
            raise ValueError(f"decoded payload must contain 1 to {MAX_STREAM_BYTES} bytes")
        if base64.b64encode(decoded).decode("ascii") != value:
            raise ValueError("payload_base64 must use canonical base64 encoding")
        return value

    def payload_bytes(self) -> bytes:
        return base64.b64decode(self.payload_base64, validate=True)


class CloseSessionInput(ListenerInput):
    session_ref: SessionRef


class CloseListenerInput(ListenerInput):
    resource_ref: ResourceRef
