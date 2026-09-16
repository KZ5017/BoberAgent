"""Transport-independent Event envelope."""

from pydantic import AwareDatetime

from ._base import ContractModel, JsonObject, SymbolicName
from .refs import DomainRef, EventRef, MissionRef


class Event(ContractModel):
    """A persistable notification carrying JSON-compatible data."""

    event_id: EventRef
    type: SymbolicName
    timestamp: AwareDatetime
    mission_ref: MissionRef
    source_ref: DomainRef
    payload: JsonObject
