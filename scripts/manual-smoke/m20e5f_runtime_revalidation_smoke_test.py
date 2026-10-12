"""Manual-only E5 intermediate pump; run against a FRESH E5-budget E3/E4 chain.

Never use the accepted v7 runtime. Never runs acquired code or finalizes E6.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from boberagent_contracts import (
    DomainRef,
    ResourceRef,
    RuntimePreparationRef,
    python_runtime_evidence_digest,
)
from boberagent_core import (
    ArtifactStorageConfiguration,
    CapabilityRegistry,
    CapabilityRouter,
    CoreArtifactReceiver,
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
from boberagent_core.preparation.runtime import CorePythonRuntimeService
from boberagent_transport.preparation_runtime import RuntimePreparationOperation
from boberagent_transport_mcp import McpTransport
from m20e3_preparation_import_smoke_test import (
    NOW,
    _configuration,
    _initialize,
    _profile,
    _require_current_permit,
)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-runtime-directory", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--allow-insecure-remote-transport", action="store_true")
    parser.add_argument("--token-environment-variable", default="BOBERAGENT_MCP_TOKEN")
    parser.add_argument("--operation", choices=["prepare", "status", "revalidate"], required=True)
    parser.add_argument(
        "--attempt-id", help="same ID for replay; NEW ID for explicit fresh revalidation"
    )
    parser.add_argument("--expect-validity", choices=["UNCHECKED", "VALID"], required=True)
    parser.add_argument("--wait-seconds", type=int, default=350)
    args = parser.parse_args()
    if args.operation != "status" and not args.attempt_id:
        parser.error("--attempt-id is required for an active operation")
    if not 1 <= args.wait_seconds <= 600:
        parser.error("--wait-seconds must be 1..600")
    return args


async def run(args: argparse.Namespace) -> None:
    if not (args.core_runtime_directory / "e3-synthetic-selection.json").is_file():
        raise ValueError("fresh E5-budget E3 import required first")
    database, selection, plan_ref = _initialize(args)
    transport = McpTransport(_configuration(args))
    saved_path = args.core_runtime_directory / "e5f-selection.json"
    try:
        selected = json.loads(selection.read_text())
        ref = RuntimePreparationRef(selected["preparation_ref"])
        with database.unit_of_work() as work:
            plan_record = work.execution_plans.get(plan_ref)
        if plan_record is None:
            raise ValueError("retained synthetic plan missing")
        policy = CorePlanPolicyService(
            database,
            PolicyProfileRegistry((_profile(plan_record.plan, approval=False),)),
            clock=lambda: NOW,
        )
        registry = CapabilityRegistry(database)
        await transport.connect()
        await CapabilityRegistrationClient(transport, registry).refresh_node(args.node_id)
        admission = CoreRuntimePreparationAdmissionService(
            database, policy, CorePlanApprovalService(database, policy, clock=lambda: NOW), registry
        )
        permit = _require_current_permit(admission.current_admission(ref), now=datetime.now(UTC))
        artifacts = CoreArtifactService(
            database,
            FilesystemArtifactStorage(
                ArtifactStorageConfiguration(root=args.core_runtime_directory / "artifacts")
            ),
        )
        dispatch = CorePreparationDispatchService(
            database,
            admission,
            registry,
            CapabilityRouter(registry, transport),
            transport,
            artifacts,
        )
        # Existing E4 publication is verified/reused; no source program is run.
        source = await dispatch.materialize_source(ref)
        runtime = CorePythonRuntimeService(dispatch)
        saved = json.loads(saved_path.read_text()) if saved_path.exists() else None
        resource = ResourceRef(saved["resource_ref"]) if saved else None
        binding = saved["binding_sha256"] if saved else None
        if args.operation != "prepare" and saved is None:
            raise ValueError("run fresh prepare first and retain its selection")
        operation = {
            "prepare": RuntimePreparationOperation.PREPARE_RUNTIME,
            "status": RuntimePreparationOperation.RUNTIME_STATUS,
            "revalidate": RuntimePreparationOperation.REVALIDATE_RUNTIME,
        }[args.operation]
        result = await runtime.exchange(
            ref,
            materialization=source,
            operation=operation,
            attempt_id=None if args.attempt_id is None else DomainRef(args.attempt_id),
            resource_ref=None if args.operation == "prepare" else resource,
            binding_sha256=None if args.operation == "prepare" else binding,
        )
        deadline = time.monotonic() + args.wait_seconds
        while result.operation_state == "ACTIVE":
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "bounded runtime operation wait elapsed; inspect retained status"
                )
            await asyncio.sleep(1)
            # Prepare replay can identify a reserved Resource before its D binding is sealed.
            result = await runtime.exchange(
                ref,
                materialization=source,
                operation=operation,
                attempt_id=None if args.attempt_id is None else DomainRef(args.attempt_id),
                resource_ref=None if args.operation == "prepare" else resource,
                binding_sha256=None if args.operation == "prepare" else binding,
            )
        if result.current is None or result.current.validity.value != args.expect_validity:
            raise ValueError("expected current validity not established")
        if result.current.failure is not None or result.current.state.value not in {
            "CREATING",
            "READY",
        }:
            raise ValueError("runtime was rejected/quarantined")
        record = dict(
            resource_ref=str(result.resource_ref),
            binding_sha256=result.current.binding_sha256,
            construction_sha256=result.construction_sha256,
        )
        if saved and saved != record:
            raise ValueError("retained Resource/binding/construction identity changed")
        if saved is None:
            saved_path.write_text(json.dumps(record, sort_keys=True) + "\n")
        # Ordinary M6 evidence synchronization, not E6 preparation finalization.
        storage = FilesystemArtifactStorage(
            ArtifactStorageConfiguration(root=args.core_runtime_directory / "artifacts")
        )
        sync = await transport.synchronize_artifacts(CoreArtifactReceiver(database, storage))
        if sync.failed:
            raise ValueError("runtime evidence Artifact synchronization failed")
        print(
            json.dumps(
                dict(
                    result="PASS",
                    preparation_ref=str(ref),
                    run_ref=str(permit.run_ref),
                    node_id=args.node_id,
                    **record,
                    operation_id=str(result.operation_id),
                    state=result.current.state.value,
                    phase=result.current.phase.value,
                    validity=result.current.validity.value,
                    evidence_sha256=None
                    if result.evidence is None
                    else python_runtime_evidence_digest(result.evidence),
                    evidence_artifact_refs=[]
                    if result.evidence is None
                    else list(result.evidence.evidence_artifact_refs),
                    execution_authorized=False,
                    preparation_terminal=False,
                    acquired_source_executed=False,
                ),
                indent=2,
            )
        )
    finally:
        await transport.disconnect()
        database.dispose()


if __name__ == "__main__":
    asyncio.run(run(arguments()))
