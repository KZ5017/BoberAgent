"""Composition root for the local Execution Node runtime."""

from __future__ import annotations

import os

from boberagent_contracts import CapabilityInvocation, CapabilityResult, JsonObject
from boberagent_sdk import UtcClock

from .browser import BrowserBackend, BrowserRuntimeManager, PlaywrightBrowserBackend
from .capabilities import (
    CapabilityAvailability,
    CapabilityLoader,
    CapabilityRuntime,
    LocalCapabilityRegistry,
    interrupted_result,
)
from .config import NodeConfiguration
from .events import EventOutbox
from .health import NodeHealth
from .identity import NodeId, NodeIdentity, load_or_create_identity
from .lifecycle import NodeLifecycle, NodeLifecycleState
from .persistence import RuntimeDatabase, RuntimeStore
from .persistence.migrations import upgrade_database
from .results import ResultOutbox
from .services import ExecutionContextFactory, LocalInvocationEnvironment
from .tools import DependencyResolver, ToolAvailability, ToolRegistry


class ExecutionNode:
    """Own and coordinate one local runtime independently of transport adapters."""

    def __init__(
        self,
        configuration: NodeConfiguration,
        *,
        browser_backend: BrowserBackend | None = None,
    ) -> None:
        self.configuration = configuration
        self.lifecycle = NodeLifecycle()
        self.identity: NodeIdentity | None = None
        self.database: RuntimeDatabase | None = None
        self.store: RuntimeStore | None = None
        self.capabilities = LocalCapabilityRegistry()
        self.tools = ToolRegistry()
        self.events: EventOutbox | None = None
        self.results: ResultOutbox | None = None
        self.runtime: CapabilityRuntime | None = None
        self.browser_runtime: BrowserRuntimeManager | None = None
        self._browser_backend = browser_backend
        self._clock = UtcClock()
        self._degraded_reasons: list[str] = []
        self._database_ready = False

    async def initialize(self) -> NodeHealth:
        """Prepare storage, recover uncertain state, and become locally available."""

        self.lifecycle.transition(NodeLifecycleState.STARTING)
        try:
            self.configuration.prepare_directories()
            configured_id = (
                None
                if self.configuration.configured_node_id is None
                else NodeId(self.configuration.configured_node_id)
            )
            self.identity = load_or_create_identity(self.configuration.identity_path, configured_id)
            self.database = RuntimeDatabase(self.configuration.database_path)
            upgrade_database(self.database)
            self._database_ready = True
            self.store = RuntimeStore(self.database)
            self.events = EventOutbox(self.store)
            self.results = ResultOutbox(self.store)

            recovered_runs, recovered_processes = self.store.recover_interrupted(self._clock.now())
            recovered_resources, recovered_sessions = (
                self.store.recover_non_restorable_browser_state(self._clock.now())
            )
            for record in recovered_runs:
                result = interrupted_result(record, self._clock.now())
                self.results.persist_terminal(
                    result,
                    finished_at=self._clock.now(),
                    error_code="INTERRUPTED_EXECUTION_STATE_UNKNOWN",
                )
            if recovered_runs or recovered_processes:
                self._degraded_reasons.append(
                    "recovered interrupted local execution state conservatively"
                )
            if recovered_resources or recovered_sessions:
                self._degraded_reasons.append(
                    "non-restorable browser Resources/Sessions were marked LOST"
                )

            CapabilityLoader().discover(self.configuration.capability_paths, self.capabilities)
            for name, configuration in sorted(self.configuration.tools.items()):
                self.tools.register(name, configuration)
            await self.tools.refresh()
            self.browser_runtime = BrowserRuntimeManager(
                store=self.store,
                tools=self.tools,
                backend=self._browser_backend or PlaywrightBrowserBackend(),
                clock=self._clock.now,
            )

            if self.capabilities.failures:
                self._degraded_reasons.append("one or more capability manifests failed")
            unavailable_tools = tuple(
                record.name
                for record in self.tools.records()
                if record.availability is ToolAvailability.UNAVAILABLE
            )
            if unavailable_tools:
                self._degraded_reasons.append(
                    "configured tools unavailable: " + ", ".join(unavailable_tools)
                )
            if not os.access(self.configuration.artifact_spool_root, os.W_OK):
                self._degraded_reasons.append("Artifact spool is not writable")

            dependencies = DependencyResolver(self.tools, self.capabilities)
            for provider in self.capabilities.providers():
                report = dependencies.evaluate(provider.definition)
                provider.apply_dependency_availability(
                    missing_required=bool(report.missing_required),
                    missing_optional=bool(report.missing_optional),
                )
            unavailable_capabilities = tuple(
                str(provider.definition.capability_id)
                for provider in self.capabilities.providers()
                if provider.availability
                in {CapabilityAvailability.UNAVAILABLE, CapabilityAvailability.DEGRADED}
            )
            if unavailable_capabilities:
                self._degraded_reasons.append(
                    "capabilities with unavailable dependencies: "
                    + ", ".join(unavailable_capabilities)
                )
            contexts = ExecutionContextFactory(
                configuration=self.configuration,
                node_id=self.identity.node_id,
                store=self.store,
                tools=self.tools,
                event_outbox=self.events,
                browser_runtime=self.browser_runtime,
            )
            self.runtime = CapabilityRuntime(
                registry=self.capabilities,
                dependencies=dependencies,
                contexts=contexts,
                store=self.store,
                results=self.results,
            )
            target = (
                NodeLifecycleState.DEGRADED if self._degraded_reasons else NodeLifecycleState.READY
            )
            self.lifecycle.transition(target)
            return self.health()
        except Exception:
            self.lifecycle.transition(NodeLifecycleState.FAILED)
            if self.database is not None:
                self.database.close()
            self._database_ready = False
            raise

    async def execute_local(
        self,
        invocation: CapabilityInvocation,
        environment: LocalInvocationEnvironment,
        *,
        invocation_fingerprint: str | None = None,
    ) -> CapabilityResult:
        """Execute through the local harness; this is intentionally not a transport API."""

        if self.lifecycle.state not in {
            NodeLifecycleState.READY,
            NodeLifecycleState.DEGRADED,
        }:
            raise RuntimeError(f"Node does not accept local invocations: {self.lifecycle.state}")
        if self.runtime is None:
            raise RuntimeError("Node runtime was not initialized")
        return await self.runtime.execute(
            invocation,
            environment,
            invocation_fingerprint=invocation_fingerprint,
        )

    def health(self) -> NodeHealth:
        if self.identity is None or self.store is None:
            raise RuntimeError("Node is not initialized")
        provider_failures = tuple(
            failure
            for provider in self.capabilities.providers()
            if (failure := provider.failure) is not None
        )
        tool_summary: JsonObject = {
            record.name: {
                "availability": record.availability.value,
                "version": record.version,
                "diagnostic": record.diagnostic,
            }
            for record in self.tools.records()
        }
        artifacts = self.store.artifact_count() if self._database_ready else 0
        pending_events = len(self.store.pending_events()) if self._database_ready else 0
        pending_results = len(self.store.pending_results()) if self._database_ready else 0
        return NodeHealth(
            node_id=self.identity.node_id,
            lifecycle=self.lifecycle.state,
            checked_at=self._clock.now(),
            database_ready=self._database_ready,
            capabilities_loaded=sum(
                provider.availability is not CapabilityAvailability.DISABLED
                for provider in self.capabilities.providers()
            ),
            capability_failures=tuple(self.capabilities.failures) + provider_failures,
            tool_summary=tool_summary,
            local_artifacts=artifacts,
            pending_events=pending_events,
            pending_results=pending_results,
            runtime_resources=self.store.runtime_resource_count(),
            runtime_sessions=self.store.runtime_session_count(),
            degraded_reasons=tuple(self._degraded_reasons),
        )

    async def shutdown(self) -> None:
        if self.lifecycle.state in {
            NodeLifecycleState.READY,
            NodeLifecycleState.DEGRADED,
        }:
            self.lifecycle.transition(NodeLifecycleState.DRAINING)
        if self.browser_runtime is not None:
            await self.browser_runtime.shutdown()
        if self.database is not None:
            self.database.close()
        self._database_ready = False
        if self.lifecycle.state in {NodeLifecycleState.DRAINING, NodeLifecycleState.FAILED}:
            self.lifecycle.transition(NodeLifecycleState.OFFLINE)
