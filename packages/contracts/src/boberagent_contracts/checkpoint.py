"""Serializable Capability continuation checkpoint."""

from pydantic import AwareDatetime

from ._base import ContractModel, JsonObject, SymbolicName
from .refs import (
    ArtifactRef,
    CapabilityRunRef,
    CheckpointRef,
    InteractionRef,
    ResourceRef,
    SessionRef,
)


class Checkpoint(ContractModel):
    """Durable logical continuation state without live runtime objects."""

    checkpoint_id: CheckpointRef
    run_ref: CapabilityRunRef
    phase: SymbolicName
    state: JsonObject
    created_at: AwareDatetime
    artifact_refs: tuple[ArtifactRef, ...] = ()
    resource_refs: tuple[ResourceRef, ...] = ()
    session_refs: tuple[SessionRef, ...] = ()
    pending_interaction_ref: InteractionRef | None = None
