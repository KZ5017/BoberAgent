"""Opt-in real Core↔Kali E4 check and harmless retained-source materialization.

Run E3's manual import first in the same dedicated Core runtime directory and
within its permit validity window. Neither mode imports nor executes PoC Python.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from boberagent_contracts import RuntimePreparationRef
from boberagent_core import (
    ArtifactStorageConfiguration,
    CapabilityRegistry,
    CapabilityRouter,
    CoreArtifactService,
    FilesystemArtifactStorage,
)
from boberagent_core.capabilities import CapabilityRegistrationClient
from boberagent_core.planning.approval import CorePlanApprovalService
from boberagent_core.planning.policy_service import CorePlanPolicyService, PolicyProfileRegistry
from boberagent_core.preparation import (
    CorePreparationDispatchService,
    CoreRuntimePreparationAdmissionService,
)
from boberagent_transport_mcp import McpTransport
from m20e3_preparation_import_smoke_test import (
    NOW,
    _configuration,
    _initialize,
    _profile,
    _require_current_permit,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-config", action="store_true")
    mode.add_argument("--real-materialization", action="store_true")
    parser.add_argument("--core-runtime-directory", required=True, type=Path)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--allow-insecure-remote-transport", action="store_true")
    parser.add_argument("--token-environment-variable", default="BOBERAGENT_MCP_TOKEN")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> None:
    if not (args.core_runtime_directory / "e3-synthetic-selection.json").exists():
        raise ValueError("E3 selection is missing; run the E3 import first")
    database, selection, plan_ref = _initialize(args)
    transport = McpTransport(_configuration(args))
    try:
        selected = json.loads(selection.read_text(encoding="utf-8"))
        ref = RuntimePreparationRef(selected["preparation_ref"])
        with database.unit_of_work() as work:
            plan_record = work.execution_plans.get(plan_ref)
        if plan_record is None:
            raise ValueError("retained synthetic plan is unavailable")
        policy = CorePlanPolicyService(
            database,
            PolicyProfileRegistry((_profile(plan_record.plan, approval=False),)),
            clock=lambda: NOW,
        )
        registry = CapabilityRegistry(database, clock=lambda: datetime.now(UTC))
        await transport.connect()
        preparation = CoreRuntimePreparationAdmissionService(
            database,
            policy,
            CorePlanApprovalService(database, policy, clock=lambda: NOW),
            registry,
            clock=lambda: datetime.now(UTC),
        )
        # Refresh transport/registry before evaluating current E2 applicability.
        await CapabilityRegistrationClient(transport, registry).refresh_node(args.node_id)
        admitted = preparation.current_admission(ref)
        permit = _require_current_permit(admitted, now=datetime.now(UTC))
        artifacts = CoreArtifactService(
            database,
            FilesystemArtifactStorage(
                ArtifactStorageConfiguration(root=args.core_runtime_directory / "artifacts")
            ),
        )
        dispatch = CorePreparationDispatchService(
            database,
            preparation,
            registry,
            CapabilityRouter(registry, transport, clock=lambda: datetime.now(UTC)),
            transport,
            artifacts,
        )
        check = await dispatch.check_materialization(ref)
        print(f"PreparationRef: {ref}")
        print(f"RunRef: {permit.run_ref}")
        print(f"Node ID: {check.node_id}")
        print(f"Raw: {check.raw_artifact_ref} sha256={check.raw_sha256}")
        print(f"Manifest: {check.manifest_artifact_ref} sha256={check.manifest_sha256}")
        print(f"Confinement: {check.confinement_backend} {check.confinement_version}")
        print("Proven E4 features: " + ", ".join(check.proven_features))
        if args.check_config:
            print("CHECK PASS: imported inputs and trusted confinement probe; no workspace created")
            return
        evidence = await dispatch.materialize_source(ref)
        print(f"Materialization ID: {evidence.materialization_id}")
        print(f"Files: {evidence.file_count}; bytes: {evidence.materialized_bytes}")
        print(f"Tree SHA-256: {evidence.tree_sha256}")
        print(f"Published source state: {evidence.state}")
        print("E4 PASS: exact retained source published; no runtime, venv or PoC execution")
    finally:
        await transport.disconnect()
        database.dispose()


if __name__ == "__main__":
    asyncio.run(_run(_arguments()))
