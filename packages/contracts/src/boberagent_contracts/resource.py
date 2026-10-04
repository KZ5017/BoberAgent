"""Logical Resource descriptor."""

from typing import Annotated

from pydantic import AwareDatetime, Field, StringConstraints

from ._base import ContractModel, JsonObject, SymbolicName
from .enums import AccessMode
from .refs import CapabilityRunRef, DomainRef, ResourceRef

# Provider labels may carry the explicit implementation version adopted by E5.
# Keep ordinary domain SymbolicName unchanged and reject paths/command syntax here.
type ResourceProviderName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*(?:@[A-Za-z0-9][A-Za-z0-9._:-]*)?$",
    ),
]


class ResourceDescriptor(ContractModel):
    """Metadata for platform-managed runtime infrastructure."""

    resource_id: ResourceRef
    resource_type: SymbolicName
    provider: ResourceProviderName
    state: SymbolicName
    owner_ref: DomainRef
    created_by_run: CapabilityRunRef
    created_at: AwareDatetime
    access_modes: tuple[AccessMode, ...] = Field(min_length=1)
    expires_at: AwareDatetime | None = None
    lifecycle_metadata: JsonObject = Field(default_factory=dict)
