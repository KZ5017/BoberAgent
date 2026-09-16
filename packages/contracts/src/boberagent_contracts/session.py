"""Logical Session descriptor."""

from pydantic import AwareDatetime, Field

from ._base import ContractModel, JsonObject, SymbolicName
from .enums import AccessMode
from .refs import (
    AccessContextRef,
    CapabilityRunRef,
    DomainRef,
    IdentityRef,
    ResourceRef,
    SessionRef,
)


class SessionDescriptor(ContractModel):
    """Metadata for a persistent stateful interaction context."""

    session_id: SessionRef
    session_type: SymbolicName
    state: SymbolicName
    provider: SymbolicName
    owner_ref: DomainRef
    created_by_run: CapabilityRunRef
    created_at: AwareDatetime
    target_ref: DomainRef | None = None
    identity_ref: IdentityRef | None = None
    access_context_ref: AccessContextRef | None = None
    resource_refs: tuple[ResourceRef, ...] = ()
    supported_operations: tuple[SymbolicName, ...] = ()
    access_modes: tuple[AccessMode, ...] = Field(min_length=1)
    lifecycle_metadata: JsonObject = Field(default_factory=dict)
