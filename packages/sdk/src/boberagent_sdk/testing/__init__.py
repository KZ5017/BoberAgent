"""Opt-in in-memory utilities for capability unit tests."""

from .context import FakeExecutionContext
from .fixtures import make_fake_context
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
    LogLevel,
    LogRecord,
    ToolInvocation,
)

__all__ = [
    "FakeArtifactService",
    "FakeCancellationService",
    "FakeCapabilityLogger",
    "FakeCheckpointService",
    "FakeClock",
    "FakeEntityReader",
    "FakeEventService",
    "FakeExecutionContext",
    "FakeInteractionService",
    "FakeProcessService",
    "FakeResourceService",
    "FakeScopeService",
    "FakeSecretService",
    "FakeSessionService",
    "FakeWorkspaceService",
    "LogLevel",
    "LogRecord",
    "ToolInvocation",
    "make_fake_context",
]
