"""Secret-safe human and JSON rendering for CLI response models."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import TextIO
from uuid import UUID

from pydantic import BaseModel, SecretStr


class OutputWriter:
    def __init__(self, stream: TextIO, *, json_output: bool) -> None:
        self._stream = stream
        self._json_output = json_output

    def emit(self, value: object) -> None:
        serialized = to_json_value(value)
        if self._json_output:
            print(
                json.dumps(serialized, indent=2, sort_keys=True, ensure_ascii=False),
                file=self._stream,
            )
            return
        for line in _human_lines(serialized):
            print(line, file=self._stream)


def to_json_value(value: object) -> object:
    if isinstance(value, SecretStr):
        return "**********"
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Path | UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [to_json_value(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"unsupported CLI output type: {type(value).__name__}")


def _human_lines(value: object, *, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, list):
        if not value:
            return [f"{prefix}No records."]
        lines: list[str] = []
        for index, item in enumerate(value):
            if index:
                lines.append("")
            if isinstance(item, dict):
                nested = _human_lines(item, indent=indent + 2)
                lines.append(f"{prefix}- {nested[0].lstrip()}")
                lines.extend(nested[1:])
            else:
                lines.append(f"{prefix}- {_scalar(item)}")
        return lines
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, dict | list):
                lines.append(f"{prefix}{key}:")
                lines.extend(_human_lines(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_scalar(item)}")
        return lines
    return [f"{prefix}{_scalar(value)}"]


def _scalar(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)
