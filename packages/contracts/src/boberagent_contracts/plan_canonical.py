"""Pure canonical serialization for typed intent; ordered collections stay ordered."""

import hashlib
import json
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from ._base import JsonValue


def canonical_value(value: object, *, exclude: frozenset[str] = frozenset()) -> JsonValue:
    """Canonicalize maps and declared sets, never all sequences indiscriminately.

    Pydantic field introspection is confined here; dynamic attributes are immediately handled
    as object, not propagated as Any. This is a digest helper, not validation/authorization.
    Exclusion applies only to the root record, so meaningful nested IDs remain pinned.
    """
    if isinstance(value, BaseModel):
        result: dict[str, JsonValue] = {}
        for name, field in type(value).model_fields.items():
            if name in exclude:
                continue
            item: object = getattr(value, name)
            normalized = canonical_value(item)
            metadata = field.json_schema_extra
            if isinstance(metadata, dict) and metadata.get("collection_semantics") == "set":
                if not isinstance(normalized, list):
                    raise TypeError("set-valued field must be a sequence")
                normalized = sorted(
                    {canonical_json(element): element for element in normalized}.values(),
                    key=canonical_json,
                )
            result[name] = normalized
        return result
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, tuple | list):
        return [canonical_value(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical maps require string keys")
        return {key: canonical_value(item) for key, item in value.items()}
    raise TypeError("unsupported canonical value")


def canonical_json(value: JsonValue) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def canonical_digest(value: BaseModel, *, exclude: frozenset[str] = frozenset()) -> str:
    return hashlib.sha256(
        canonical_json(canonical_value(value, exclude=exclude)).encode()
    ).hexdigest()
