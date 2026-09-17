"""Explicit local Node lifecycle transitions."""

from enum import StrEnum


class NodeLifecycleState(StrEnum):
    STARTING = "STARTING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    DRAINING = "DRAINING"
    OFFLINE = "OFFLINE"
    FAILED = "FAILED"


_TRANSITIONS: dict[NodeLifecycleState, frozenset[NodeLifecycleState]] = {
    NodeLifecycleState.OFFLINE: frozenset({NodeLifecycleState.STARTING}),
    NodeLifecycleState.STARTING: frozenset(
        {NodeLifecycleState.READY, NodeLifecycleState.DEGRADED, NodeLifecycleState.FAILED}
    ),
    NodeLifecycleState.READY: frozenset(
        {NodeLifecycleState.DEGRADED, NodeLifecycleState.DRAINING, NodeLifecycleState.FAILED}
    ),
    NodeLifecycleState.DEGRADED: frozenset(
        {NodeLifecycleState.READY, NodeLifecycleState.DRAINING, NodeLifecycleState.FAILED}
    ),
    NodeLifecycleState.DRAINING: frozenset({NodeLifecycleState.OFFLINE, NodeLifecycleState.FAILED}),
    NodeLifecycleState.FAILED: frozenset({NodeLifecycleState.OFFLINE, NodeLifecycleState.STARTING}),
}


class NodeLifecycle:
    def __init__(self) -> None:
        self._state = NodeLifecycleState.OFFLINE

    @property
    def state(self) -> NodeLifecycleState:
        return self._state

    def transition(self, target: NodeLifecycleState) -> None:
        if target not in _TRANSITIONS[self._state]:
            raise ValueError(f"invalid Node lifecycle transition: {self._state} -> {target}")
        self._state = target
