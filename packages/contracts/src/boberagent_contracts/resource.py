"""Logical Resource descriptor."""

from pydantic import AwareDatetime, Field

from ._base import ContractModel, JsonObject, SymbolicName
from .enums import AccessMode
from .refs import CapabilityRunRef, DomainRef, ResourceRef


class ResourceDescriptor(ContractModel):
    """Metadata for platform-managed runtime infrastructure."""

    resource_id: ResourceRef
    resource_type: SymbolicName
    provider: SymbolicName
    state: SymbolicName
    owner_ref: DomainRef
    created_by_run: CapabilityRunRef
    created_at: AwareDatetime
    access_modes: tuple[AccessMode, ...] = Field(min_length=1)
    expires_at: AwareDatetime | None = None
    lifecycle_metadata: JsonObject = Field(default_factory=dict)
