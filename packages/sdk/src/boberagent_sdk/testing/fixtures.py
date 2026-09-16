"""Small construction helpers usable by capability test suites."""

from datetime import UTC, datetime

from boberagent_contracts import CapabilityRunRef, MissionRef

from boberagent_sdk.context import InvocationContext, MissionContext

from .context import FakeExecutionContext
from .services import FakeClock


def make_fake_context(
    *,
    capability_id: str = "test.capability",
    operation: str = "execute",
    run_ref: CapabilityRunRef | None = None,
    mission_ref: MissionRef | None = None,
    now: datetime | None = None,
) -> FakeExecutionContext:
    """Create a deterministic context while keeping logical IDs easy to override."""

    selected_run = run_ref or CapabilityRunRef("run-test")
    selected_mission = mission_ref or MissionRef("mission-test")
    invocation = InvocationContext(
        run_id=selected_run,
        capability_id=capability_id,
        operation=operation,
        mission_ref=selected_mission,
    )
    mission = MissionContext(mission_ref=selected_mission, name="SDK test mission")
    clock = FakeClock(now or datetime(2026, 1, 1, tzinfo=UTC))
    return FakeExecutionContext(invocation=invocation, mission=mission, clock=clock)
