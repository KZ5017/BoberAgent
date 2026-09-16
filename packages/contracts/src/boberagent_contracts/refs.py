"""Stable, infrastructure-independent logical reference types."""

from __future__ import annotations

import re
from typing import Self

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

_REFERENCE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._:/-]{0,254}$")


class DomainRef(str):
    """Base logical reference serialized as a validated JSON string.

    Concrete subclasses are distinct at runtime and to static type checkers. Plain serialized
    strings remain accepted because transports do not carry Python class identity.
    """

    def __new__(cls, value: str) -> Self:
        if not isinstance(value, str):
            raise TypeError("domain references must be strings")
        if _REFERENCE_PATTERN.fullmatch(value) is None:
            raise ValueError(
                "domain references must start with a letter and contain only letters, digits, "
                "'.', '_', ':', '/', or '-'"
            )
        return str.__new__(cls, value)

    @classmethod
    def _reject_other_reference_type(cls, value: object) -> object:
        if cls is not DomainRef and isinstance(value, DomainRef) and type(value) is not cls:
            raise ValueError(f"expected {cls.__name__}, received {type(value).__name__}")
        return value

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: object,
        _handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        guarded_string = core_schema.no_info_before_validator_function(
            cls._reject_other_reference_type,
            core_schema.str_schema(
                strict=True,
                min_length=1,
                max_length=255,
                pattern=_REFERENCE_PATTERN.pattern,
            ),
        )
        return core_schema.no_info_after_validator_function(
            cls,
            guarded_string,
            serialization=core_schema.to_string_ser_schema(),
        )


class MissionRef(DomainRef):
    """Reference to a Core-owned Mission."""


class AssetRef(DomainRef):
    """Reference to a Core-owned Asset."""


class ApplicationRef(DomainRef):
    """Reference to a Core-owned Application."""


class ServiceRef(DomainRef):
    """Reference to a Core-owned Service."""


class IdentityRef(DomainRef):
    """Reference to a Core-owned Identity."""


class CredentialRef(DomainRef):
    """Reference to a Core-owned Credential."""


class SecretRef(DomainRef):
    """Reference to secret material held by the Secret Store."""


class AccessContextRef(DomainRef):
    """Reference to a Core-owned AccessContext."""


class ArtifactRef(DomainRef):
    """Reference to persistent evidence or generated data."""


class StorageRef(DomainRef):
    """Opaque logical reference used by an Artifact storage provider."""


class ResourceRef(DomainRef):
    """Reference to managed runtime infrastructure."""


class SessionRef(DomainRef):
    """Reference to a persistent interaction context."""


class CapabilityRunRef(DomainRef):
    """Reference to one concrete Capability execution."""


class WorkflowRunRef(DomainRef):
    """Reference to a Workflow execution."""


class ObservationRef(DomainRef):
    """Reference to an immutable Observation."""


class FindingRef(DomainRef):
    """Reference to an assessment interpretation."""


class EffectRef(DomainRef):
    """Reference to an assessment-induced state change."""


class ExecutionPlanRef(DomainRef):
    """Reference to structured execution intent."""


class EventRef(DomainRef):
    """Reference to an Event envelope."""


class InteractionRef(DomainRef):
    """Reference to an Interaction request/response exchange."""


class CheckpointRef(DomainRef):
    """Reference to durable logical continuation state."""
