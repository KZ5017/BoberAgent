"""Local health snapshot without a transport endpoint."""

from boberagent_contracts import JsonObject
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .identity import NodeId
from .lifecycle import NodeLifecycleState


class NodeHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: NodeId
    lifecycle: NodeLifecycleState
    checked_at: AwareDatetime
    database_ready: bool
    capabilities_loaded: int = Field(ge=0)
    capability_failures: tuple[str, ...] = ()
    tool_summary: JsonObject = Field(default_factory=dict)
    local_artifacts: int = Field(ge=0)
    pending_events: int = Field(ge=0)
    pending_results: int = Field(ge=0)
    runtime_resources: int = Field(ge=0)
    runtime_sessions: int = Field(ge=0)
    degraded_reasons: tuple[str, ...] = ()
