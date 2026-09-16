"""Composed in-memory ExecutionContext for capability unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import TracebackType

from boberagent_contracts import CapabilityRunRef, MissionRef

from boberagent_sdk.context import InvocationContext, MissionContext

from .services import (
    FakeArtifactService,
    FakeCancellationService,
    FakeCapabilityLogger,
    FakeCheckpointService,
    FakeClock,
    FakeEntityReader,
    FakeEventService,
    FakeInteractionService,
    FakeProcessService,
    FakeResourceService,
    FakeScopeService,
    FakeSecretService,
    FakeSessionService,
    FakeWorkspaceService,
)

_DEFAULT_TIME = datetime(2026, 1, 1, tzinfo=UTC)


class FakeExecutionContext:
    """Complete SDK test environment with no Core or Execution Node dependency."""

    def __init__(
        self,
        *,
        invocation: InvocationContext | None = None,
        mission: MissionContext | None = None,
        clock: FakeClock | None = None,
    ) -> None:
        selected_invocation = invocation or InvocationContext(
            run_id=CapabilityRunRef("run-test"),
            capability_id="test.capability",
            operation="execute",
            mission_ref=MissionRef("mission-test"),
        )
        selected_mission = mission or MissionContext(
            mission_ref=selected_invocation.mission_ref,
            name="SDK test mission",
        )
        if selected_mission.mission_ref != selected_invocation.mission_ref:
            raise ValueError("MissionContext must match InvocationContext.mission_ref")

        self._invocation = selected_invocation
        self._mission = selected_mission
        self._clock = clock or FakeClock(_DEFAULT_TIME)
        self._scope = FakeScopeService()
        self._entities = FakeEntityReader()
        self._processes = FakeProcessService()
        self._workspace = FakeWorkspaceService(selected_invocation.run_id)
        self._resources = FakeResourceService(selected_invocation.run_id, self._clock)
        self._sessions = FakeSessionService()
        self._artifacts = FakeArtifactService(selected_invocation.run_id, self._clock)
        self._secrets = FakeSecretService()
        self._interactions = FakeInteractionService()
        self._checkpoints = FakeCheckpointService(selected_invocation.run_id)
        self._events = FakeEventService(
            mission_ref=selected_invocation.mission_ref,
            run_ref=selected_invocation.run_id,
            clock=self._clock,
        )
        self._logger = FakeCapabilityLogger()
        self._cancellation = FakeCancellationService()
        self._closed = False

    @property
    def invocation(self) -> InvocationContext:
        return self._invocation

    @property
    def mission(self) -> MissionContext:
        return self._mission

    @property
    def scope(self) -> FakeScopeService:
        return self._scope

    @property
    def entities(self) -> FakeEntityReader:
        return self._entities

    @property
    def processes(self) -> FakeProcessService:
        return self._processes

    @property
    def workspace(self) -> FakeWorkspaceService:
        return self._workspace

    @property
    def resources(self) -> FakeResourceService:
        return self._resources

    @property
    def sessions(self) -> FakeSessionService:
        return self._sessions

    @property
    def artifacts(self) -> FakeArtifactService:
        return self._artifacts

    @property
    def secrets(self) -> FakeSecretService:
        return self._secrets

    @property
    def interactions(self) -> FakeInteractionService:
        return self._interactions

    @property
    def checkpoints(self) -> FakeCheckpointService:
        return self._checkpoints

    @property
    def events(self) -> FakeEventService:
        return self._events

    @property
    def logger(self) -> FakeCapabilityLogger:
        return self._logger

    @property
    def cancellation(self) -> FakeCancellationService:
        return self._cancellation

    @property
    def clock(self) -> FakeClock:
        return self._clock

    def close(self) -> None:
        if not self._closed:
            self._workspace.close()
            self._closed = True

    async def __aenter__(self) -> FakeExecutionContext:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback
        self.close()
