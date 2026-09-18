"""Validated MCP Streamable HTTP adapter configuration."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


def _is_loopback(host: str | None) -> bool:
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class McpClientConfiguration(BaseModel):
    """Core-side connection settings for one explicit Execution Node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint_url: str = Field(min_length=1)
    node_id: str = Field(min_length=3, max_length=255)
    bearer_token: SecretStr
    request_timeout_seconds: float = Field(default=30.0, gt=0, le=3600)
    verify_tls: bool | Path = True
    allow_insecure_remote_transport: bool = False
    outbound_queue_capacity: int = Field(default=100, ge=1, le=100_000)
    poll_batch_size: int = Field(default=100, ge=1, le=10_000)

    @model_validator(mode="after")
    def validate_endpoint_security(self) -> McpClientConfiguration:
        if not self.bearer_token.get_secret_value():
            raise ValueError("bearer_token must not be empty")
        parsed = urlparse(self.endpoint_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise ValueError("endpoint_url must be an absolute HTTP(S) URL")
        if (
            parsed.scheme == "http"
            and not _is_loopback(parsed.hostname)
            and not self.allow_insecure_remote_transport
        ):
            raise ValueError("plaintext MCP is restricted to loopback unless explicitly overridden")
        return self


class McpServerConfiguration(BaseModel):
    """Execution Node listener settings with conservative network defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bind_host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=0, le=65535)
    bearer_token: SecretStr
    tls_certificate: Path | None = None
    tls_private_key: Path | None = None
    allow_insecure_remote_transport: bool = False
    max_request_body_bytes: int = Field(default=4 * 1024 * 1024, ge=1024)
    outbound_batch_size: int = Field(default=100, ge=1, le=10_000)

    @model_validator(mode="after")
    def validate_listener_security(self) -> McpServerConfiguration:
        if not self.bearer_token.get_secret_value():
            raise ValueError("bearer_token must not be empty")
        if (self.tls_certificate is None) != (self.tls_private_key is None):
            raise ValueError("TLS certificate and private key must be configured together")
        if (
            not _is_loopback(self.bind_host)
            and self.tls_certificate is None
            and not self.allow_insecure_remote_transport
        ):
            raise ValueError(
                "a non-loopback MCP listener requires TLS or an explicit insecure override"
            )
        return self

    @property
    def scheme(self) -> str:
        return "https" if self.tls_certificate is not None else "http"
