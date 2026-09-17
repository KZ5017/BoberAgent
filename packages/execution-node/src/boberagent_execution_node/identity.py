"""Stable, node-owned logical identity."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from boberagent_contracts import DomainRef
from pydantic import BaseModel, ConfigDict


class NodeId(DomainRef):
    """Execution-Node-owned identifier; not part of Capability Contract v1."""


class NodeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: NodeId


def load_or_create_identity(path: Path, configured_node_id: NodeId | None = None) -> NodeIdentity:
    """Load an identity or atomically create it on first initialization."""

    if path.exists():
        identity = NodeIdentity.model_validate_json(path.read_text(encoding="utf-8"))
        if configured_node_id is not None and identity.node_id != configured_node_id:
            raise ValueError("configured NodeId does not match persisted Node identity")
        return identity

    identity = NodeIdentity(node_id=configured_node_id or NodeId(f"node-{uuid4()}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(identity.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return identity
