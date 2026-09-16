"""Structured capability logging interface."""

from typing import Protocol

from boberagent_contracts import JsonValue


class CapabilityLogger(Protocol):
    def debug(self, message: str, **fields: JsonValue) -> None: ...

    def info(self, message: str, **fields: JsonValue) -> None: ...

    def warning(self, message: str, **fields: JsonValue) -> None: ...

    def error(self, message: str, **fields: JsonValue) -> None: ...
