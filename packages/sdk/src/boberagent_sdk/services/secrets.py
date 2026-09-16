"""Purpose-aware Secret access without casual plaintext representation."""

from __future__ import annotations

from typing import Protocol

from boberagent_contracts import JsonObject, SecretRef


class SensitiveValue:
    """Short-lived secret bytes with explicit unsafe access and redacted display."""

    __slots__ = ("__value",)

    def __init__(self, value: bytes) -> None:
        self.__value = bytes(value)

    @classmethod
    def from_text(cls, value: str, *, encoding: str = "utf-8") -> SensitiveValue:
        return cls(value.encode(encoding))

    def reveal_bytes(self) -> bytes:
        """Explicitly access secret bytes for an authorized operation."""

        return self.__value

    def reveal_text(self, *, encoding: str = "utf-8") -> str:
        """Explicitly decode secret material for an authorized operation."""

        return self.__value.decode(encoding)

    def __repr__(self) -> str:
        return "SensitiveValue(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"

    def __format__(self, format_spec: str) -> str:
        del format_spec
        return "<redacted>"


class SecretService(Protocol):
    async def resolve(self, secret_ref: SecretRef, *, purpose: str) -> SensitiveValue: ...

    async def store(
        self,
        *,
        value: SensitiveValue,
        secret_type: str,
        metadata: JsonObject | None = None,
    ) -> SecretRef: ...
