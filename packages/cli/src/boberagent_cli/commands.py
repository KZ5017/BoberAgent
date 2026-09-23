"""Thin command handlers delegating behavior to public Core services."""

from __future__ import annotations

import base64
import json
from argparse import Namespace
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from boberagent_contracts import (
    AssetRef,
    CapabilityRunRef,
    CredentialRef,
    InteractionRef,
    InteractionType,
    JsonObject,
    MissionRef,
    SecretRef,
    WorkflowRunRef,
)
from boberagent_core import (
    Asset,
    CapabilityRegistry,
    CoreCredentialService,
    CoreDatabase,
    CoreInteractionService,
    CorePersistence,
    CoreSecretService,
    Mission,
    ResultIngestionService,
    WorkflowDefinition,
    WorkflowService,
    current_revision,
    head_revision,
    upgrade_database,
)
from pydantic import TypeAdapter, ValidationError

from .composition import (
    RemoteNodeConfiguration,
    WorkflowSessionFactory,
)
from .errors import CliInvalidInput, CliNotFound
from .output import OutputWriter

_json_object_adapter: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class _InteractionCommandSession(Protocol):
    interactions: CoreInteractionService


@dataclass(slots=True)
class CommandContext:
    database: CoreDatabase
    output: OutputWriter
    environment: Mapping[str, str]
    workflow_sessions: WorkflowSessionFactory

    @property
    def core(self) -> CorePersistence:
        return CorePersistence(self.database)


def core_init(database: CoreDatabase, output: OutputWriter) -> None:
    upgrade_database(database)
    output.emit(
        {
            "database_url": database.config.url,
            "revision": current_revision(database),
            "schema_current": current_revision(database) == head_revision(),
        }
    )


def core_status(database_path: Path, output: OutputWriter) -> None:
    resolved = database_path.resolve()
    if not resolved.exists():
        output.emit(
            {
                "database_path": str(resolved),
                "exists": False,
                "revision": None,
                "expected_revision": head_revision(),
                "schema_current": False,
            }
        )
        return
    if not resolved.is_file():
        raise CliInvalidInput("Core database path is not a regular file")
    from boberagent_core import DatabaseConfig

    database = CoreDatabase(DatabaseConfig.sqlite(resolved))
    try:
        revision = current_revision(database)
    finally:
        database.dispose()
    output.emit(
        {
            "database_path": str(resolved),
            "exists": True,
            "revision": revision,
            "expected_revision": head_revision(),
            "schema_current": revision == head_revision(),
        }
    )


def mission_create(arguments: Namespace, context: CommandContext) -> None:
    mission = Mission(
        mission_ref=MissionRef(arguments.mission_ref),
        status=arguments.status,
        created_at=datetime.now(UTC),
        name=arguments.name,
        metadata=_json_object(arguments.metadata),
    )
    context.core.create_mission(mission)
    context.output.emit(mission)


def mission_show(arguments: Namespace, context: CommandContext) -> None:
    mission = context.core.get_mission(MissionRef(arguments.mission_ref))
    if mission is None:
        raise CliNotFound(f"Mission not found: {arguments.mission_ref}")
    context.output.emit(mission)


def mission_list(_arguments: Namespace, context: CommandContext) -> None:
    context.output.emit(context.core.list_missions())


def asset_add(arguments: Namespace, context: CommandContext) -> None:
    mission_ref = MissionRef(arguments.mission_ref)
    if context.core.get_mission(mission_ref) is None:
        raise CliNotFound(f"Mission not found: {mission_ref}")
    asset = Asset(
        asset_ref=AssetRef(arguments.asset_ref),
        mission_ref=mission_ref,
        kind=arguments.kind,
        primary_address=arguments.address,
        created_at=datetime.now(UTC),
        metadata=_json_object(arguments.metadata),
    )
    context.core.create_asset(asset)
    context.output.emit(asset)


def asset_show(arguments: Namespace, context: CommandContext) -> None:
    asset = context.core.get_asset(AssetRef(arguments.asset_ref))
    if asset is None:
        raise CliNotFound(f"Asset not found: {arguments.asset_ref}")
    context.output.emit(asset)


def asset_list(arguments: Namespace, context: CommandContext) -> None:
    mission_ref = MissionRef(arguments.mission_ref)
    if context.core.get_mission(mission_ref) is None:
        raise CliNotFound(f"Mission not found: {mission_ref}")
    context.output.emit(context.core.list_assets(mission_ref))


def provider_list(arguments: Namespace, context: CommandContext) -> None:
    registry = CapabilityRegistry(context.database, mark_persisted_stale=False)
    if arguments.capability_id is None:
        providers = tuple(
            provider
            for definition in registry.list_capabilities()
            for provider in registry.list_providers(str(definition.capability_id))
        )
    else:
        providers = registry.list_providers(arguments.capability_id)
    context.output.emit(providers)


def provider_show(arguments: Namespace, context: CommandContext) -> None:
    registry = CapabilityRegistry(context.database, mark_persisted_stale=False)
    provider = registry.get_provider(UUID(arguments.provider_id))
    if provider is None:
        raise CliNotFound(f"Capability provider not found: {arguments.provider_id}")
    context.output.emit(provider)


async def workflow_start(arguments: Namespace, context: CommandContext) -> None:
    definition = _workflow_definition(arguments.definition)
    remote = _remote_configuration(arguments, context.environment)
    async with context.workflow_sessions(context.database, remote) as session:
        execution = await session.workflows.start(
            definition,
            MissionRef(arguments.mission_ref),
            workflow_run_ref=(
                None if arguments.workflow_ref is None else WorkflowRunRef(arguments.workflow_ref)
            ),
        )
    context.output.emit(execution)


def workflow_status(arguments: Namespace, context: CommandContext) -> None:
    execution = WorkflowService(context.database).inspect(WorkflowRunRef(arguments.workflow_ref))
    if execution is None:
        raise CliNotFound(f"Workflow not found: {arguments.workflow_ref}")
    context.output.emit(execution)


async def workflow_advance(arguments: Namespace, context: CommandContext) -> None:
    remote = _remote_configuration(arguments, context.environment)
    workflow_ref = WorkflowRunRef(arguments.workflow_ref)
    async with context.workflow_sessions(context.database, remote) as session:
        await session.receive_pending()
        execution = await session.workflows.advance(workflow_ref)
    context.output.emit(execution)


def workflow_cancel(arguments: Namespace, context: CommandContext) -> None:
    execution = WorkflowService(context.database).cancel(WorkflowRunRef(arguments.workflow_ref))
    context.output.emit(execution)


def run_show(arguments: Namespace, context: CommandContext) -> None:
    run_ref = CapabilityRunRef(arguments.run_ref)
    run = context.core.get_run(run_ref)
    if run is None:
        raise CliNotFound(f"CapabilityRun not found: {arguments.run_ref}")
    ingestion = ResultIngestionService(context.database).get_ingestion(run_ref)
    context.output.emit({"run": run, "result_ingestion": ingestion})


def service_list(arguments: Namespace, context: CommandContext) -> None:
    asset_ref = AssetRef(arguments.asset_ref)
    if context.core.get_asset(asset_ref) is None:
        raise CliNotFound(f"Asset not found: {arguments.asset_ref}")
    context.output.emit(context.core.services_for_asset(asset_ref))


def secret_list(arguments: Namespace, context: CommandContext) -> None:
    mission_ref = MissionRef(arguments.mission_ref)
    context.output.emit(CoreSecretService(context.database).list_for_mission(mission_ref))


def secret_show(arguments: Namespace, context: CommandContext) -> None:
    mission_ref = MissionRef(arguments.mission_ref)
    secret = CoreSecretService(context.database).get(SecretRef(arguments.secret_ref))
    if secret is None or secret.mission_ref != mission_ref:
        raise CliNotFound(f"Secret not found for Mission: {arguments.secret_ref}")
    context.output.emit(secret)


def secret_reveal(arguments: Namespace, context: CommandContext) -> None:
    secret_ref = SecretRef(arguments.secret_ref)
    revealed = CoreSecretService(context.database).reveal_for_operator(
        secret_ref,
        mission_ref=MissionRef(arguments.mission_ref),
    )
    context.output.emit(
        {
            "secret_ref": str(secret_ref),
            "value": _render_revealed(revealed.reveal_bytes(), arguments.encoding),
            "encoding": arguments.encoding,
        }
    )


def credential_list(arguments: Namespace, context: CommandContext) -> None:
    context.output.emit(
        CoreCredentialService(context.database).list_for_mission(MissionRef(arguments.mission_ref))
    )


def credential_show(arguments: Namespace, context: CommandContext) -> None:
    mission_ref = MissionRef(arguments.mission_ref)
    credential = CoreCredentialService(context.database).get(
        CredentialRef(arguments.credential_ref)
    )
    if credential is None or credential.mission_ref != mission_ref:
        raise CliNotFound(f"Credential not found for Mission: {arguments.credential_ref}")
    context.output.emit(credential)


def credential_reveal(arguments: Namespace, context: CommandContext) -> None:
    credential_ref = CredentialRef(arguments.credential_ref)
    revealed = CoreCredentialService(context.database).reveal(
        credential_ref,
        role=arguments.role,
        mission_ref=MissionRef(arguments.mission_ref),
    )
    context.output.emit(
        {
            "credential_ref": str(credential_ref),
            "role": arguments.role,
            "value": _render_revealed(revealed.reveal_bytes(), arguments.encoding),
            "encoding": arguments.encoding,
        }
    )


def interaction_list(arguments: Namespace, context: CommandContext) -> None:
    service = CoreInteractionService(context.database)
    context.output.emit(service.list_all() if arguments.all else service.list_pending())


def interaction_show(arguments: Namespace, context: CommandContext) -> None:
    record = CoreInteractionService(context.database).get(InteractionRef(arguments.interaction_ref))
    if record is None:
        raise CliNotFound(f"Interaction not found: {arguments.interaction_ref}")
    context.output.emit(record)


async def interaction_respond(arguments: Namespace, context: CommandContext) -> None:
    interaction_ref = InteractionRef(arguments.interaction_ref)
    stored = CoreInteractionService(context.database).get(interaction_ref)
    if stored is None:
        raise CliNotFound(f"Interaction not found: {interaction_ref}")
    interaction_type = stored.request.interaction_type
    if arguments.yes or arguments.no:
        if interaction_type is not InteractionType.CONFIRMATION:
            raise CliInvalidInput("--yes/--no require a confirmation Interaction")
        value: bool | str = bool(arguments.yes)
    elif arguments.text is not None:
        if interaction_type is not InteractionType.TEXT:
            raise CliInvalidInput("--text requires a text Interaction")
        value = arguments.text
    elif arguments.choice is not None:
        if interaction_type is not InteractionType.SINGLE_CHOICE:
            raise CliInvalidInput("--choice requires a single-choice Interaction")
        value = arguments.choice
    else:
        raise CliInvalidInput("one response value is required")
    remote = _remote_configuration(arguments, context.environment)
    async with context.workflow_sessions(context.database, remote) as session:
        await session.receive_pending()
        interaction_session = cast(_InteractionCommandSession, session)
        record = await interaction_session.interactions.respond(interaction_ref, value)
    context.output.emit(record)


def _json_object(value: str) -> JsonObject:
    try:
        parsed = json.loads(value)
        return _json_object_adapter.validate_python(parsed)
    except (json.JSONDecodeError, ValidationError) as error:
        raise CliInvalidInput("metadata must be a JSON object") from error


def _render_revealed(value: bytes, encoding: str) -> str:
    if encoding == "base64":
        return base64.b64encode(value).decode("ascii")
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CliInvalidInput("Secret is not UTF-8 text; use --encoding base64") from error


def _workflow_definition(path: Path) -> WorkflowDefinition:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CliInvalidInput(f"could not read Workflow definition: {path}") from error
    try:
        return WorkflowDefinition.model_validate_json(content)
    except ValidationError as error:
        raise CliInvalidInput("Workflow definition failed validation") from error


def _remote_configuration(
    arguments: Namespace,
    environment: Mapping[str, str],
) -> RemoteNodeConfiguration:
    return RemoteNodeConfiguration.from_values(
        endpoint_url=arguments.node_url,
        node_id=arguments.node_id,
        bearer_token_environment=arguments.bearer_token_env,
        environment=environment,
        request_timeout_seconds=arguments.request_timeout,
        verify_tls=not arguments.no_verify_tls,
        allow_insecure_remote_transport=arguments.allow_insecure_remote_transport,
    )
