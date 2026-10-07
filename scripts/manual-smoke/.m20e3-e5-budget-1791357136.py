"""Opt-in E3 Core/real-MCP/Kali import of harmless retained synthetic Artifacts.

The source is never extracted, installed, imported as Python, or executed. This
manual-only harness reuses the repository's synthetic D7 fixture constructors.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from boberagent_cli.operator_env import operator_environment
from boberagent_contracts import ExecutionPlanRef, PreparationPermit, RuntimePreparationRef
from boberagent_contracts.runtime_preparation import ConfinementFeature, PreparationAction
from boberagent_core import (
    ArtifactStorageConfiguration,
    CapabilityRegistry,
    CapabilityRouter,
    CoreArtifactService,
    CoreDatabase,
    DatabaseConfig,
    FilesystemArtifactStorage,
    upgrade_database,
)
from boberagent_core.capabilities import CapabilityRegistrationClient
from boberagent_core.capabilities.models import provider_id_for
from boberagent_core.planning.approval import CorePlanApprovalService
from boberagent_core.planning.construction import CoreExecutionPlanningService
from boberagent_core.planning.policy_service import CorePlanPolicyService, PolicyProfileRegistry
from boberagent_core.preparation import (
    CorePreparationDispatchService,
    CoreRuntimePreparationAdmissionService,
    PreparationAdmission,
    PreparationRequest,
)
from boberagent_transport import PREPARATION_IMPORT_PROTOCOL_VERSION
from boberagent_transport_mcp import McpClientConfiguration, McpTransport
from pydantic import SecretStr

_TEST_FIXTURES = Path(__file__).resolve().parents[2] / "packages/core/tests"
sys.path.insert(0, str(_TEST_FIXTURES))

from planning_construction_fixtures import prepared  # noqa: E402
from test_core_poc_acquisition import NOW  # noqa: E402
from test_planning_policy import _profile  # noqa: E402
from boberagent_contracts import PreparationBudgets


def _budgets() -> PreparationBudgets:
    return PreparationBudgets(
        max_imported_artifact_bytes=1_000_000,
        max_materialized_bytes=1_000_000,
        max_file_count=15_000,
        max_path_depth=16,
        max_temporary_bytes=256 * 1024 * 1024,
        max_preparation_write_bytes=1024 * 1024 * 1024,
        max_processes=11,
        max_process_runtime_seconds=60,
        max_total_runtime_seconds=900,
        max_captured_output_bytes=200_000,
        max_memory_bytes=256 * 1024 * 1024,
    )



def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check-config", action="store_true", help="prepare/check fixture; no transfer"
    )
    mode.add_argument("--real-artifact-import", action="store_true", help="authorize exact import")
    parser.add_argument("--core-runtime-directory", required=True, type=Path)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--allow-insecure-remote-transport", action="store_true")
    parser.add_argument("--token-environment-variable", default="BOBERAGENT_MCP_TOKEN")
    return parser.parse_args()


def _configuration(args: argparse.Namespace) -> McpClientConfiguration:
    environment = operator_environment(os.environ, project_root=Path(__file__).resolve().parents[2])
    token = environment.get(args.token_environment_variable)
    if not token:
        raise ValueError(f"unset bearer-token variable: {args.token_environment_variable}")
    return McpClientConfiguration(
        endpoint_url=args.endpoint,
        node_id=args.node_id,
        bearer_token=SecretStr(token),
        verify_tls=args.ca_file if args.ca_file is not None else True,
        allow_insecure_remote_transport=args.allow_insecure_remote_transport,
    )


def _initialize(args: argparse.Namespace) -> tuple[CoreDatabase, Path, ExecutionPlanRef]:
    root: Path = args.core_runtime_directory
    if not root.is_absolute():
        raise ValueError("--core-runtime-directory must be absolute")
    root.mkdir(parents=True, exist_ok=True)
    selection = root / "e3-synthetic-selection.json"
    database_path = root / "core.sqlite3"
    if database_path.exists() and not selection.exists():
        raise ValueError(
            "existing Core database has no E3 fixture selection; use a dedicated directory"
        )
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database)
        if selection.exists():
            selected = json.loads(selection.read_text(encoding="utf-8"))
            if selected["node_id"] != args.node_id:
                raise ValueError("persisted fixture is bound to a different Node")
            plan_ref = ExecutionPlanRef(selected["plan_ref"])
        else:
            # The existing D7 fixtures make a harmless retained ZIP and complete
            # C/D evidence entirely offline. Nothing here executes that source.
            _chain, construction = prepared(database, root)
            built = CoreExecutionPlanningService(database, clock=lambda: NOW).construct(
                construction
            )
            plan = built.attempt.finalized_plan
            if plan is None:
                raise ValueError("synthetic D7 fixture did not produce a valid plan")
            plan_ref = plan.execution_plan_id
        return database, selection, plan_ref
    except BaseException:
        database.dispose()
        raise


def _require_current_permit(
    admitted: PreparationAdmission | None, *, now: datetime
) -> PreparationPermit:
    if admitted is None or admitted.permit is None:
        raise ValueError("E2 attempt/permit is unavailable")
    permit = admitted.permit
    remaining = max(0, math.ceil((permit.expires_at - now).total_seconds()))
    print(f"Permit not_before: {permit.not_before.isoformat()}")
    print(f"Permit expires_at: {permit.expires_at.isoformat()}")
    print(f"Permit remaining validity: {remaining}s")
    if now < permit.not_before:
        raise ValueError("PreparationPermit is not yet valid; no Artifact Import attempted")
    if now >= permit.expires_at:
        raise ValueError("PreparationPermit expired; no Artifact Import attempted")
    if remaining <= 60:
        print("Permit validity warning: under 60s remain; import/replay may not finish in time")
    if not admitted.current_applicable:
        raise ValueError("E2 attempt/permit is not currently applicable for another reason")
    return permit


async def _run(
    args: argparse.Namespace, database: CoreDatabase, selection: Path, plan_ref: ExecutionPlanRef
) -> None:
    root: Path = args.core_runtime_directory
    database_path = root / "core.sqlite3"
    transport: McpTransport | None = None
    try:
        transport = McpTransport(_configuration(args))
        selected = json.loads(selection.read_text(encoding="utf-8")) if selection.exists() else None
        with database.unit_of_work() as work:
            plan_record = work.execution_plans.get(plan_ref)
        if plan_record is None:
            raise ValueError("fixture ExecutionPlan is unavailable")
        plan = plan_record.plan
        policy = CorePlanPolicyService(
            database, PolicyProfileRegistry((_profile(plan, approval=False),)), clock=lambda: NOW
        )
        if not selection.exists():
            policy.evaluate(plan_ref)
        registry = CapabilityRegistry(database, clock=lambda: datetime.now(UTC))
        await transport.connect()
        advertisement, _providers = await CapabilityRegistrationClient(
            transport, registry
        ).refresh_node(args.node_id)
        if PREPARATION_IMPORT_PROTOCOL_VERSION not in advertisement.preparation_import_versions:
            raise ValueError("Node lacks E3 import protocol support")
        preparation = CoreRuntimePreparationAdmissionService(
            database,
            policy,
            CorePlanApprovalService(database, policy, clock=lambda: NOW),
            registry,
            clock=lambda: datetime.now(UTC),
        )
        if selected is not None:
            ref = RuntimePreparationRef(selected["preparation_ref"])
            admitted = preparation.current_admission(ref)
        else:
            request = PreparationRequest(
                mission_ref=plan.mission_ref,
                plan_ref=plan_ref,
                node_id=args.node_id,
                provider_id=provider_id_for(args.node_id, "runtime.prepare"),
                profile_id="m20-e-python-stdlib-kali",
                profile_version="1",
                budgets=_budgets(),
                confinement_features=tuple(ConfinementFeature),
                actions=tuple(PreparationAction),
            )
            admitted = preparation.admit(request)
        permit = _require_current_permit(admitted, now=datetime.now(UTC))
        print(f"Permit ref: {permit.permit_ref}")
        artifacts = CoreArtifactService(
            database,
            FilesystemArtifactStorage(ArtifactStorageConfiguration(root=root / "artifacts")),
        )
        pins = permit.spec.source.plan_source
        for ref in (pins.raw_artifact_ref, pins.manifest_artifact_ref):
            if not artifacts.content_available(ref):
                raise ValueError(f"Core retained Artifact unavailable: {ref}")
        if selected is None:
            selection.write_text(
                json.dumps(
                    {
                        "node_id": args.node_id,
                        "plan_ref": str(plan_ref),
                        "preparation_ref": str(admitted.attempt.preparation_ref),
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        print(f"Core database: {database_path}")
        print(f"Node: {args.node_id}; protocol: {PREPARATION_IMPORT_PROTOCOL_VERSION}")
        print(f"Preparation: {admitted.attempt.preparation_ref}; Run: {permit.run_ref}")
        print(f"Raw: {pins.raw_artifact_ref} sha256={pins.raw_sha256} size={pins.raw_size_bytes}")
        print(
            f"Manifest: {pins.manifest_artifact_ref} "
            f"sha256={pins.manifest_sha256} size={permit.spec.source.manifest_size_bytes}"
        )
        if args.check_config:
            print("CHECK PASS: current E2 authority and Core bytes available; zero bytes imported")
            return
        dispatch = CorePreparationDispatchService(
            database,
            preparation,
            registry,
            CapabilityRouter(registry, transport, clock=lambda: datetime.now(UTC)),
            transport,
            artifacts,
        )
        first = await dispatch.dispatch_and_import(admitted.attempt.preparation_ref)
        if any(item.state.value != "VERIFIED" for item in first):
            raise ValueError("Node did not verify both imported Artifacts")
        await transport.disconnect()
        await transport.connect()
        _require_current_permit(
            preparation.current_admission(admitted.attempt.preparation_ref),
            now=datetime.now(UTC),
        )
        replay = await dispatch.dispatch_and_import(admitted.attempt.preparation_ref)
        if replay != first:
            raise ValueError("reconnected identical import did not reuse durable identity")
        print("IMPORT PASS: both exact Artifacts verified; reconnect/replay reused identities")
        print("No extraction, workspace, Resource, venv, process or PoC execution was requested")
    finally:
        if transport is not None:
            await transport.disconnect()
        database.dispose()


if __name__ == "__main__":
    arguments = _arguments()
    core, state_file, selected_plan = _initialize(arguments)
    asyncio.run(_run(arguments, core, state_file, selected_plan))
