"""Production Node adapters used to construct one Run-scoped ExecutionContext."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from boberagent_contracts import (
    AssetRef,
    Checkpoint,
    CheckpointRef,
    CredentialRef,
    DomainRef,
    JsonObject,
    JsonValue,
    SecretRef,
)
from boberagent_sdk import (
    AssetSnapshot,
    CredentialSnapshot,
    DependencyError,
    EntitySnapshot,
    InvocationContext,
    MissionContext,
    ScopeViolation,
    SecretService,
    SensitiveValue,
    UtcClock,
)
from boberagent_transport import SecretGrant

from boberagent_execution_node.artifacts import LocalArtifactSpool
from boberagent_execution_node.browser import BrowserRuntimeManager
from boberagent_execution_node.config import NodeConfiguration
from boberagent_execution_node.events import EventOutbox, NodeEventService
from boberagent_execution_node.identity import NodeId
from boberagent_execution_node.interactions import InteractionRuntime, NodeInteractionService
from boberagent_execution_node.listener import ListenerRuntimeManager
from boberagent_execution_node.persistence import RuntimeStore
from boberagent_execution_node.processes import ManagedProcessService, NodeCancellationService
from boberagent_execution_node.tools import ToolRegistry
from boberagent_execution_node.workspace import ManagedWorkspaceService

from .resource_sessions import NodeResourceService, NodeSessionService


class LocalScopeService:
    """Explicit scope projection supplied by the local Milestone 4 harness."""

    def __init__(self, assets: set[AssetRef], addresses: set[str]) -> None:
        self._assets = frozenset(assets)
        self._addresses = frozenset(addresses)

    async def contains_asset(self, asset_ref: AssetRef) -> bool:
        return asset_ref in self._assets

    async def assert_asset_allowed(self, asset_ref: AssetRef) -> None:
        if not await self.contains_asset(asset_ref):
            raise ScopeViolation(f"Asset is outside local scope projection: {asset_ref}")

    async def contains_address(self, address: str) -> bool:
        return address in self._addresses

    async def assert_address_allowed(self, address: str) -> None:
        if not await self.contains_address(address):
            raise ScopeViolation(f"Address is outside local scope projection: {address}")


class LocalEntityReader:
    def __init__(
        self,
        entities: tuple[EntitySnapshot | AssetSnapshot | CredentialSnapshot, ...],
    ) -> None:
        self._entities = {str(entity.ref): entity.model_copy(deep=True) for entity in entities}

    async def get(self, ref: DomainRef) -> EntitySnapshot | AssetSnapshot | CredentialSnapshot:
        try:
            return self._entities[str(ref)].model_copy(deep=True)
        except KeyError as error:
            raise DependencyError(
                f"Entity is absent from local invocation projection: {ref}"
            ) from error

    async def asset(self, asset_ref: AssetRef) -> AssetSnapshot:
        entity = await self.get(asset_ref)
        if not isinstance(entity, AssetSnapshot):
            raise DependencyError(f"Entity is not an Asset snapshot: {asset_ref}")
        return entity

    async def credential(self, credential_ref: CredentialRef) -> CredentialSnapshot:
        entity = await self.get(credential_ref)
        if not isinstance(entity, CredentialSnapshot):
            raise DependencyError(f"Entity is not a Credential snapshot: {credential_ref}")
        return entity


class SecretRedactor:
    """Run-local best-effort redaction for values explicitly resolved by a capability."""

    def __init__(self) -> None:
        self._known_text: set[str] = set()

    def register(self, value: bytes) -> None:
        try:
            decoded = value.decode("utf-8")
        except UnicodeDecodeError:
            return
        if decoded:
            self._known_text.add(decoded)

    def text(self, value: str) -> str:
        redacted = value
        for secret in sorted(self._known_text, key=len, reverse=True):
            redacted = redacted.replace(secret, "<REDACTED>")
        return redacted

    def json(self, value: JsonValue) -> JsonValue:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.json(item) for item in value]
        if isinstance(value, dict):
            return {key: self.json(item) for key, item in value.items()}
        return value


class RunSecretService:
    """Resolve only values explicitly granted to this invocation; never enumerate them."""

    def __init__(self, grants: tuple[SecretGrant, ...], redactor: SecretRedactor) -> None:
        self._grants = {str(grant.secret_ref): grant for grant in grants}
        self._redactor = redactor

    async def resolve(self, secret_ref: SecretRef, *, purpose: str) -> SensitiveValue:
        if not purpose:
            raise ValueError("Secret resolution requires an explicit purpose")
        try:
            grant = self._grants[str(secret_ref)]
        except KeyError as error:
            raise DependencyError(
                f"Secret was not authorized for this CapabilityRun: {secret_ref}"
            ) from error
        if purpose != grant.authorized_purpose:
            raise DependencyError(
                f"Secret was not authorized for purpose {purpose!r}: {secret_ref}"
            )
        value = bytes(grant.value)
        self._redactor.register(value)
        return SensitiveValue(value)

    async def store(
        self,
        *,
        value: SensitiveValue,
        secret_type: str,
        metadata: JsonObject | None = None,
    ) -> SecretRef:
        del value, secret_type, metadata
        raise DependencyError(
            "Capability-side Secret creation requires a canonical Core delivery path"
        )


class UnavailableCheckpointService:
    async def save(self, checkpoint: Checkpoint) -> None:
        del checkpoint
        raise DependencyError("durable continuation is not implemented in Milestone 4")

    async def load(self, checkpoint_ref: CheckpointRef) -> Checkpoint | None:
        del checkpoint_ref
        raise DependencyError("durable continuation is not implemented in Milestone 4")


class NodeCapabilityLogger:
    def __init__(
        self,
        *,
        node_id: NodeId,
        invocation: InvocationContext,
        logger: logging.Logger,
        redactor: SecretRedactor,
    ) -> None:
        self._logger = logger
        self._redactor = redactor
        self._base: JsonObject = {
            "node_id": str(node_id),
            "run_id": str(invocation.run_id),
            "capability_id": invocation.capability_id,
            "operation": invocation.operation,
        }

    def _log(self, level: int, message: str, fields: dict[str, JsonValue]) -> None:
        safe_fields = {
            key: self._redactor.json(value) for key, value in {**self._base, **fields}.items()
        }
        self._logger.log(level, "%s | %s", self._redactor.text(message), safe_fields)

    def debug(self, message: str, **fields: JsonValue) -> None:
        self._log(logging.DEBUG, message, fields)

    def info(self, message: str, **fields: JsonValue) -> None:
        self._log(logging.INFO, message, fields)

    def warning(self, message: str, **fields: JsonValue) -> None:
        self._log(logging.WARNING, message, fields)

    def error(self, message: str, **fields: JsonValue) -> None:
        self._log(logging.ERROR, message, fields)


class NodeExecutionContext:
    """Concrete Run-scoped implementation of the SDK ExecutionContext protocol."""

    def __init__(
        self,
        *,
        invocation: InvocationContext,
        mission: MissionContext,
        scope: LocalScopeService,
        entities: LocalEntityReader,
        processes: ManagedProcessService,
        workspace: ManagedWorkspaceService,
        resources: NodeResourceService,
        sessions: NodeSessionService,
        artifacts: LocalArtifactSpool,
        secrets: SecretService,
        events: NodeEventService,
        interactions: NodeInteractionService,
        logger: NodeCapabilityLogger,
        cancellation: NodeCancellationService,
    ) -> None:
        self.invocation = invocation
        self.mission = mission
        self.scope = scope
        self.entities = entities
        self.processes = processes
        self.workspace = workspace
        self.resources = resources
        self.sessions = sessions
        self.artifacts = artifacts
        self.secrets = secrets
        self.interactions = interactions
        self.checkpoints = UnavailableCheckpointService()
        self.events = events
        self.logger = logger
        self.cancellation = cancellation
        self.clock = UtcClock()


@dataclass(frozen=True, slots=True)
class LocalInvocationEnvironment:
    mission: MissionContext
    allowed_assets: frozenset[AssetRef] = frozenset()
    allowed_addresses: frozenset[str] = frozenset()
    entities: tuple[EntitySnapshot | AssetSnapshot | CredentialSnapshot, ...] = ()
    secret_grants: tuple[SecretGrant, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextBundle:
    context: NodeExecutionContext
    events: NodeEventService
    cancellation: NodeCancellationService


class ExecutionContextFactory:
    def __init__(
        self,
        *,
        configuration: NodeConfiguration,
        node_id: NodeId,
        store: RuntimeStore,
        tools: ToolRegistry,
        event_outbox: EventOutbox,
        browser_runtime: BrowserRuntimeManager,
        listener_runtime: ListenerRuntimeManager,
        interaction_runtime: InteractionRuntime,
    ) -> None:
        self._configuration = configuration
        self._node_id = node_id
        self._store = store
        self._tools = tools
        self._event_outbox = event_outbox
        self._browser_runtime = browser_runtime
        self._listener_runtime = listener_runtime
        self._interaction_runtime = interaction_runtime

    def create(
        self,
        invocation: InvocationContext,
        environment: LocalInvocationEnvironment,
    ) -> ContextBundle:
        if environment.mission.mission_ref != invocation.mission_ref:
            raise ValueError("local Mission projection does not match invocation")
        clock = UtcClock()
        cancellation = NodeCancellationService()
        workspace = ManagedWorkspaceService(
            root=self._configuration.workspace_root,
            store=self._store,
            run_ref=invocation.run_id,
            clock=clock.now,
        )
        artifacts = LocalArtifactSpool(
            root=self._configuration.artifact_spool_root,
            allowed_source_roots=(
                self._configuration.workspace_root,
                self._configuration.process_output_root,
            ),
            store=self._store,
            run_ref=invocation.run_id,
            clock=clock.now,
        )
        events = NodeEventService(
            outbox=self._event_outbox,
            mission_ref=invocation.mission_ref,
            run_ref=invocation.run_id,
            clock=clock.now,
        )
        resources = NodeResourceService(
            run_ref=invocation.run_id,
            store=self._store,
            browser=self._browser_runtime,
            listener=self._listener_runtime,
        )
        sessions = NodeSessionService(
            run_ref=invocation.run_id,
            store=self._store,
            browser=self._browser_runtime,
            listener=self._listener_runtime,
        )
        redactor = SecretRedactor()
        context = NodeExecutionContext(
            invocation=invocation,
            mission=environment.mission,
            scope=LocalScopeService(
                set(environment.allowed_assets), set(environment.allowed_addresses)
            ),
            entities=LocalEntityReader(environment.entities),
            processes=ManagedProcessService(
                tools=self._tools,
                store=self._store,
                run_ref=invocation.run_id,
                cancellation=cancellation,
                artifacts=artifacts,
                output_root=self._configuration.process_output_root,
                clock=clock.now,
                terminate_grace_seconds=(self._configuration.process_terminate_grace_seconds),
                max_inline_output_bytes=(self._configuration.max_inline_process_output_bytes),
            ),
            workspace=workspace,
            resources=resources,
            sessions=sessions,
            artifacts=artifacts,
            secrets=RunSecretService(environment.secret_grants, redactor),
            events=events,
            interactions=NodeInteractionService(
                runtime=self._interaction_runtime,
                run_ref=invocation.run_id,
                mission_ref=invocation.mission_ref,
                workflow_run_ref=invocation.workflow_run_ref,
                events=events,
            ),
            logger=NodeCapabilityLogger(
                node_id=self._node_id,
                invocation=invocation,
                logger=logging.getLogger("boberagent.execution_node.capability"),
                redactor=redactor,
            ),
            cancellation=cancellation,
        )
        return ContextBundle(context=context, events=events, cancellation=cancellation)
