"""Adapter-local MCP carrier models; these are not domain Contract types."""

from __future__ import annotations

from enum import StrEnum

from boberagent_contracts import ArtifactRef
from pydantic import BaseModel, ConfigDict, Field


class McpConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"


class McpModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )


class ArtifactReadRequest(McpModel):
    artifact_ref: ArtifactRef
    offset: int = Field(ge=0)
    max_bytes: int = Field(ge=1, le=1024 * 1024)


class ArtifactReadResponse(McpModel):
    artifact_ref: ArtifactRef
    offset: int = Field(ge=0)
    data: bytes
    end_of_artifact: bool


class ArtifactSyncSummary(McpModel):
    attempted: int = Field(ge=0)
    synchronized: int = Field(ge=0)
    failed: int = Field(ge=0)
