"""Standard-library command parser and deterministic CLI error boundary."""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import TextIO

from boberagent_core import (
    CapabilityRoutingError,
    CoreDatabase,
    DatabaseConfig,
    InteractionConflict,
    InteractionNotFound,
    InteractionStateError,
    PersistenceIntegrityError,
    SecretAccessDenied,
    WorkflowDefinitionConflict,
    WorkflowNotFound,
    WorkflowStateError,
    current_revision,
    head_revision,
)
from boberagent_transport import TransportError
from pydantic import ValidationError

from . import commands
from .commands import CommandContext
from .composition import WorkflowSessionFactory, mcp_workflow_session
from .errors import (
    CliDomainConflict,
    CliError,
    CliInvalidInput,
    CliNotFound,
    ExitCode,
)
from .operator_env import operator_environment
from .output import OutputWriter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="boberagent",
        description="Thin operator CLI for BoberAgent Core",
    )
    parser.add_argument(
        "--database",
        required=True,
        type=Path,
        help="explicit Core SQLite database path",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--node-url", help="explicit MCP Streamable HTTP endpoint")
    parser.add_argument("--node-id", help="explicit Execution Node identity")
    parser.add_argument(
        "--bearer-token-env",
        default="BOBERAGENT_MCP_BEARER_TOKEN",
        help="environment variable containing the MCP bearer token",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=30.0,
        help="MCP request timeout in seconds",
    )
    parser.add_argument(
        "--allow-insecure-remote-transport",
        action="store_true",
        help="explicitly allow plaintext HTTP to a non-loopback Node",
    )
    parser.add_argument(
        "--no-verify-tls",
        action="store_true",
        help="disable TLS certificate verification for this command",
    )
    groups = parser.add_subparsers(dest="group", required=True)

    core = groups.add_parser("core", help="Core database lifecycle and status")
    core_actions = core.add_subparsers(dest="action", required=True)
    core_actions.add_parser("init", help="create or upgrade the explicit Core database")
    core_actions.add_parser("status", help="inspect Core database status without mutation")

    mission = groups.add_parser("mission", help="Mission persistence")
    mission_actions = mission.add_subparsers(dest="action", required=True)
    mission_create = mission_actions.add_parser("create", help="create a Mission")
    mission_create.add_argument("--mission-ref", required=True)
    mission_create.add_argument("--name")
    mission_create.add_argument("--status", default="ACTIVE")
    mission_create.add_argument("--metadata", default="{}", help="JSON object")
    mission_show = mission_actions.add_parser("show", help="show a Mission")
    mission_show.add_argument("mission_ref")
    mission_actions.add_parser("list", help="list Missions")

    asset = groups.add_parser("asset", help="Mission-owned Assets")
    asset_actions = asset.add_subparsers(dest="action", required=True)
    asset_add = asset_actions.add_parser("add", help="add an Asset")
    asset_add.add_argument("--asset-ref", required=True)
    asset_add.add_argument("--mission", dest="mission_ref", required=True)
    asset_add.add_argument("--address", required=True)
    asset_add.add_argument("--kind", default="host")
    asset_add.add_argument("--metadata", default="{}", help="JSON object")
    asset_show = asset_actions.add_parser("show", help="show an Asset")
    asset_show.add_argument("asset_ref")
    asset_list = asset_actions.add_parser("list", help="list Assets for a Mission")
    asset_list.add_argument("--mission", dest="mission_ref", required=True)

    provider = groups.add_parser("provider", help="persisted Capability providers")
    provider_actions = provider.add_subparsers(dest="action", required=True)
    provider_list = provider_actions.add_parser("list", help="list providers")
    provider_list.add_argument("--capability", dest="capability_id")
    provider_show = provider_actions.add_parser("show", help="show a provider")
    provider_show.add_argument("provider_id")

    workflow = groups.add_parser("workflow", help="durable sequential Workflows")
    workflow_actions = workflow.add_subparsers(dest="action", required=True)
    workflow_start = workflow_actions.add_parser("start", help="start a Workflow")
    workflow_start.add_argument("--mission", dest="mission_ref", required=True)
    workflow_start.add_argument("--definition", required=True, type=Path)
    workflow_start.add_argument("--workflow-ref")
    workflow_status = workflow_actions.add_parser("status", help="inspect a Workflow")
    workflow_status.add_argument("workflow_ref")
    workflow_advance = workflow_actions.add_parser("advance", help="pump a Workflow once")
    workflow_advance.add_argument("workflow_ref")
    workflow_cancel = workflow_actions.add_parser("cancel", help="cancel future Workflow steps")
    workflow_cancel.add_argument("workflow_ref")

    run_parser = groups.add_parser("run", help="CapabilityRun inspection")
    run_actions = run_parser.add_subparsers(dest="action", required=True)
    run_show = run_actions.add_parser("show", help="show a CapabilityRun and Result")
    run_show.add_argument("run_ref")

    service = groups.add_parser("service", help="materialized Service state")
    service_actions = service.add_subparsers(dest="action", required=True)
    service_list = service_actions.add_parser("list", help="list Services for an Asset")
    service_list.add_argument("--asset", dest="asset_ref", required=True)

    secret = groups.add_parser("secret", help="canonical Mission-owned Secrets")
    secret_actions = secret.add_subparsers(dest="action", required=True)
    secret_list = secret_actions.add_parser("list", help="list Secret metadata")
    secret_list.add_argument("--mission", dest="mission_ref", required=True)
    secret_show = secret_actions.add_parser("show", help="show Secret metadata")
    secret_show.add_argument("secret_ref")
    secret_show.add_argument("--mission", dest="mission_ref", required=True)
    secret_reveal = secret_actions.add_parser("reveal", help="deliberately reveal one Secret value")
    secret_reveal.add_argument("secret_ref")
    secret_reveal.add_argument("--mission", dest="mission_ref", required=True)
    secret_reveal.add_argument("--encoding", choices=("text", "base64"), default="text")

    credential = groups.add_parser("credential", help="Mission-owned Credential metadata")
    credential_actions = credential.add_subparsers(dest="action", required=True)
    credential_list = credential_actions.add_parser("list", help="list Credentials")
    credential_list.add_argument("--mission", dest="mission_ref", required=True)
    credential_show = credential_actions.add_parser("show", help="show a Credential")
    credential_show.add_argument("credential_ref")
    credential_show.add_argument("--mission", dest="mission_ref", required=True)
    credential_reveal = credential_actions.add_parser(
        "reveal", help="deliberately reveal one Credential Secret role"
    )
    credential_reveal.add_argument("credential_ref")
    credential_reveal.add_argument("--mission", dest="mission_ref", required=True)
    credential_reveal.add_argument("--role", required=True)
    credential_reveal.add_argument("--encoding", choices=("text", "base64"), default="text")

    interaction = groups.add_parser("interaction", help="durable human interactions")
    interaction_actions = interaction.add_subparsers(dest="action", required=True)
    interaction_list = interaction_actions.add_parser("list", help="list pending interactions")
    interaction_list.add_argument("--all", action="store_true", help="include terminal records")
    interaction_show = interaction_actions.add_parser("show", help="show an interaction")
    interaction_show.add_argument("interaction_ref")
    interaction_respond = interaction_actions.add_parser("respond", help="answer an interaction")
    interaction_respond.add_argument("interaction_ref")
    values = interaction_respond.add_mutually_exclusive_group(required=True)
    values.add_argument("--yes", action="store_true")
    values.add_argument("--no", action="store_true")
    values.add_argument("--text")
    values.add_argument("--choice")
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO,
    stderr: TextIO,
    environment: Mapping[str, str] | None = None,
    workflow_sessions: WorkflowSessionFactory = mcp_workflow_session,
) -> int:
    parser = build_parser()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            arguments = parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else int(ExitCode.INVALID_INPUT)

    output = OutputWriter(stdout, json_output=arguments.json)
    database: CoreDatabase | None = None
    try:
        if arguments.group == "core" and arguments.action == "status":
            commands.core_status(arguments.database, output)
            return int(ExitCode.SUCCESS)

        database_path = arguments.database.resolve()
        if arguments.group != "core" or arguments.action != "init":
            _require_current_database(database_path)
        else:
            database_path.parent.mkdir(parents=True, exist_ok=True)
        database = CoreDatabase(DatabaseConfig.sqlite(database_path))

        if arguments.group == "core" and arguments.action == "init":
            commands.core_init(database, output)
            return int(ExitCode.SUCCESS)

        context = CommandContext(
            database=database,
            output=output,
            environment=os.environ if environment is None else environment,
            workflow_sessions=workflow_sessions,
        )
        _dispatch(arguments, context)
        return int(ExitCode.SUCCESS)
    except CliError as error:
        print(f"error: {error}", file=stderr)
        return int(error.exit_code)
    except KeyError as error:
        print(f"error: not found: {_key_error_text(error)}", file=stderr)
        return int(ExitCode.NOT_FOUND)
    except (PersistenceIntegrityError, WorkflowDefinitionConflict) as error:
        print(f"error: conflict: {error}", file=stderr)
        return int(ExitCode.DOMAIN_CONFLICT)
    except WorkflowNotFound as error:
        print(f"error: {error}", file=stderr)
        return int(ExitCode.NOT_FOUND)
    except (WorkflowStateError, CapabilityRoutingError) as error:
        print(f"error: state conflict: {error}", file=stderr)
        return int(ExitCode.DOMAIN_CONFLICT)
    except InteractionNotFound as error:
        print(f"error: {error}", file=stderr)
        return int(ExitCode.NOT_FOUND)
    except (InteractionConflict, InteractionStateError) as error:
        print(f"error: interaction conflict: {error}", file=stderr)
        return int(ExitCode.DOMAIN_CONFLICT)
    except SecretAccessDenied:
        print("error: secret access denied", file=stderr)
        return int(ExitCode.DOMAIN_CONFLICT)
    except TransportError as error:
        print(f"error: transport failure ({error.code})", file=stderr)
        return int(ExitCode.TRANSPORT_FAILURE)
    except ValidationError:
        print("error: input failed validation", file=stderr)
        return int(ExitCode.INVALID_INPUT)
    except (ValueError, OSError) as error:
        print(f"error: invalid input: {error}", file=stderr)
        return int(ExitCode.INVALID_INPUT)
    except Exception as error:
        print(f"error: internal failure ({type(error).__name__})", file=stderr)
        return int(ExitCode.INTERNAL_ERROR)
    finally:
        if database is not None:
            database.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    import sys

    try:
        environment = operator_environment(os.environ, project_root=Path.cwd())
    except (OSError, ValueError):
        print("error: could not load local environment configuration", file=sys.stderr)
        return int(ExitCode.INVALID_INPUT)
    return run(argv, stdout=sys.stdout, stderr=sys.stderr, environment=environment)


def _dispatch(arguments: argparse.Namespace, context: CommandContext) -> None:
    handlers = {
        ("mission", "create"): commands.mission_create,
        ("mission", "show"): commands.mission_show,
        ("mission", "list"): commands.mission_list,
        ("asset", "add"): commands.asset_add,
        ("asset", "show"): commands.asset_show,
        ("asset", "list"): commands.asset_list,
        ("provider", "list"): commands.provider_list,
        ("provider", "show"): commands.provider_show,
        ("workflow", "status"): commands.workflow_status,
        ("workflow", "cancel"): commands.workflow_cancel,
        ("run", "show"): commands.run_show,
        ("service", "list"): commands.service_list,
        ("secret", "list"): commands.secret_list,
        ("secret", "show"): commands.secret_show,
        ("secret", "reveal"): commands.secret_reveal,
        ("credential", "list"): commands.credential_list,
        ("credential", "show"): commands.credential_show,
        ("credential", "reveal"): commands.credential_reveal,
        ("interaction", "list"): commands.interaction_list,
        ("interaction", "show"): commands.interaction_show,
    }
    async_handlers = {
        ("workflow", "start"): commands.workflow_start,
        ("workflow", "advance"): commands.workflow_advance,
        ("interaction", "respond"): commands.interaction_respond,
    }
    key = (arguments.group, arguments.action)
    handler = handlers.get(key)
    if handler is not None:
        handler(arguments, context)
        return
    async_handler = async_handlers.get(key)
    if async_handler is not None:
        asyncio.run(async_handler(arguments, context))
        return
    raise CliDomainConflict(f"unsupported command: {arguments.group} {arguments.action}")


def _require_current_database(path: Path) -> None:
    if not path.exists():
        raise CliNotFound(f"Core database does not exist: {path}; run 'core init'")
    if not path.is_file():
        raise CliInvalidInput("Core database path is not a regular file")
    database = CoreDatabase(DatabaseConfig.sqlite(path))
    try:
        revision = current_revision(database)
    finally:
        database.dispose()
    if revision != head_revision():
        raise CliInvalidInput(
            f"Core database revision is {revision or 'unversioned'}; run 'core init' to upgrade"
        )


def _key_error_text(error: KeyError) -> str:
    return str(error.args[0]) if error.args else "unknown object"
