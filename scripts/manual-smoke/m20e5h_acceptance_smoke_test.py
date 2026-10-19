"""Manual-only final E5 acceptance. Never executes acquired source or completes E6."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from _m20e5h_support import (
    AcceptanceFailure,
    PreflightRecord,
    Record,
    fresh_directory,
    non_actions,
    read_record,
    require,
    write_record,
)
from boberagent_cli.operator_env import operator_environment
from boberagent_contracts import (
    CapabilityRunStatus,
    DomainRef,
    PreparationPermit,
    PythonRuntimeEvidence,
    PythonRuntimeFailure,
    RuntimePreparationRef,
    python_runtime_evidence_digest,
)
from boberagent_core import (
    ArtifactStorageConfiguration,
    CapabilityRegistry,
    CapabilityRouter,
    CoreArtifactReceiver,
    CoreArtifactService,
    CoreDatabase,
    DatabaseConfig,
    FilesystemArtifactStorage,
    upgrade_database,
)
from boberagent_core.capabilities import CapabilityRegistrationClient
from boberagent_core.planning.approval import CorePlanApprovalService
from boberagent_core.planning.policy_service import CorePlanPolicyService, PolicyProfileRegistry
from boberagent_core.preparation import (
    CorePreparationDispatchService,
    CoreRuntimePreparationAdmissionService,
    PreparationDispatchError,
    PreparationRequest,
)
from boberagent_core.preparation.runtime import CorePythonRuntimeService
from boberagent_transport import MaterializationEvidence, TransportError
from boberagent_transport.preparation_runtime import (
    PythonRuntimeAccepted,
    RuntimePreparationOperation,
)
from boberagent_transport_mcp import McpClientConfiguration, McpTransport
from pydantic import SecretStr

# Same test-only D setup boundary as E3/G, never imported acquired source.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/core/tests"))
from m20e5g_fixtures import establish_d
from test_core_poc_acquisition import NOW
from test_planning_policy import _profile


def configuration(args: argparse.Namespace) -> McpClientConfiguration:
    environment = operator_environment(os.environ, project_root=Path(__file__).resolve().parents[2])
    token = environment.get(args.token_environment_variable)
    require(token, "MCP_BEARER_ENVIRONMENT_REQUIRED")
    assert token is not None
    return McpClientConfiguration(
        endpoint_url=args.endpoint,
        node_id=args.node_id,
        bearer_token=SecretStr(token),
        verify_tls=args.ca_file if args.ca_file is not None else True,
        allow_insecure_remote_transport=args.allow_insecure_remote_transport,
    )


class Selection(Record):
    request: PreparationRequest
    preparation_ref: RuntimePreparationRef


class Checkpoint(Record):
    selection: Selection
    source: MaterializationEvidence
    prepared: PythonRuntimeAccepted
    first: PythonRuntimeAccepted


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check-config", action="store_true", help="Kali: fresh, Resource-free preflight"
    )
    mode.add_argument(
        "--real-runtime-preparation", action="store_true", help="WSL: fresh Core admission"
    )
    mode.add_argument(
        "--restart-revalidation", action="store_true", help="WSL: after explicit Node restart"
    )
    mode.add_argument(
        "--node-report", action="store_true", help="Kali: passive ledger/source audit"
    )
    for name in (
        "node-runtime-directory",
        "core-runtime-directory",
        "runtime-confinement-config",
        "python-distribution-config",
        "trusted-helper",
        "node-preflight",
        "expected-runtime",
        "ca-file",
    ):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--bubblewrap", type=Path, default=Path("/usr/bin/bwrap"))
    parser.add_argument("--endpoint")
    parser.add_argument("--node-id")
    parser.add_argument("--token-environment-variable", default="BOBERAGENT_MCP_TOKEN")
    parser.add_argument("--allow-insecure-remote-transport", action="store_true")
    parser.add_argument("--resource-ref")
    parser.add_argument("--stage", choices=("before-restart", "after-revalidation"))
    parser.add_argument("--wait-seconds", type=int, default=350)
    args = parser.parse_args(argv)
    required = (
        (
            "node_runtime_directory",
            "runtime_confinement_config",
            "python_distribution_config",
            "trusted_helper",
        )
        if args.check_config
        else ("node_runtime_directory", "resource_ref", "stage", "expected_runtime")
        if args.node_report
        else ("core_runtime_directory", "endpoint", "node_id", "node_preflight")
    )
    for name in required:
        if getattr(args, name) is None:
            parser.error("--" + name.replace("_", "-") + " is required for this mode")
    if not 1 <= args.wait_seconds <= 600:
        parser.error("--wait-seconds must be 1..600")
    for name in ("node_runtime_directory", "core_runtime_directory"):
        value = getattr(args, name)
        if value is not None and not value.is_absolute():
            parser.error("--" + name.replace("_", "-") + " must be absolute")
    return args


class CoreCase:
    """Manual composition only; owns no domain transitions or transport semantics."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.host = read_record(args.node_preflight, PreflightRecord)
        require(self.host.node_id == args.node_id, "NODE_PREFLIGHT_IDENTITY_CONFLICT")
        require(
            not self.host.ready and not self.host.resource_created,
            "RESOURCE_FREE_PREFLIGHT_REQUIRED",
        )
        root = args.core_runtime_directory
        self.root: Path = root
        if args.real_runtime_preparation:
            fresh_directory(root)
        else:
            require((root / "e5h-first.json").is_file(), "EXISTING_H_CORE_REQUIRED")
        self.database = CoreDatabase(DatabaseConfig.sqlite(root / "core.sqlite3"))
        try:
            upgrade_database(self.database)
            self.old = (
                None
                if args.real_runtime_preparation
                else read_record(root / "e5h-first.json", Checkpoint)
            )
            if self.old is None:
                self.policy, self.request = establish_d(self.database, root, args.node_id)
            else:
                self.request = self.old.selection.request
                require(self.request.node_id == args.node_id, "RESTART_NODE_IDENTITY_CONFLICT")
                with self.database.unit_of_work() as work:
                    plan = work.execution_plans.get(self.request.plan_ref)
                require(plan is not None, "RETAINED_PLAN_MISSING")
                assert plan
                self.policy = CorePlanPolicyService(
                    self.database,
                    PolicyProfileRegistry((_profile(plan.plan, approval=False),)),
                    clock=lambda: NOW,
                )
        except BaseException:
            self.database.dispose()
            raise

    def compose(self, transport: McpTransport) -> None:
        self.transport = transport
        self.registry = CapabilityRegistry(self.database)
        self.admission = CoreRuntimePreparationAdmissionService(
            self.database,
            self.policy,
            CorePlanApprovalService(self.database, self.policy, clock=lambda: NOW),
            self.registry,
        )
        self.storage = FilesystemArtifactStorage(
            ArtifactStorageConfiguration(root=self.root / "artifacts")
        )
        self.artifacts = CoreArtifactService(self.database, self.storage)
        self.dispatch = CorePreparationDispatchService(
            self.database,
            self.admission,
            self.registry,
            CapabilityRouter(self.registry, transport),
            transport,
            self.artifacts,
        )
        self.runtime = CorePythonRuntimeService(self.dispatch)

    async def exchange(
        self,
        ref: RuntimePreparationRef,
        source: MaterializationEvidence,
        operation: RuntimePreparationOperation,
        label: str | None,
        previous: PythonRuntimeAccepted | None = None,
    ) -> PythonRuntimeAccepted:
        deadline = asyncio.get_running_loop().time() + self.args.wait_seconds
        while True:
            response = await self.runtime.exchange(
                ref,
                materialization=source,
                operation=operation,
                attempt_id=None if label is None else DomainRef(label),
                resource_ref=None if previous is None else previous.resource_ref,
                binding_sha256=None
                if previous is None or previous.current is None
                else previous.current.binding_sha256,
            )
            if operation is RuntimePreparationOperation.RUNTIME_STATUS:
                return response
            require(
                response.operation_state not in {"FAILED", "INTERRUPTED"},
                "RUNTIME_OPERATION_FAILED",
            )
            if response.operation_state == "COMPLETED" and response.construction_sha256:
                return response
            require(asyncio.get_running_loop().time() < deadline, "RUNTIME_WAIT_EXPIRED")
            await asyncio.sleep(0.5)

    def validate(
        self, result: PythonRuntimeAccepted, permit: PreparationPermit, validity: str
    ) -> None:
        require(
            result.current and result.evidence and result.construction_sha256,
            "RUNTIME_EVIDENCE_INCOMPLETE",
        )
        assert result.current and result.evidence
        require(
            result.current.validity.value == validity and result.current.failure is None,
            "UNEXPECTED_CURRENT_VALIDITY",
        )
        if validity == "VALID":
            require(
                result.current.state.value == "READY" and result.current.phase.value == "PUBLISHED",
                "RUNTIME_NOT_PUBLISHED",
            )
        binding = result.evidence.binding
        require(
            binding.request.spec == permit.spec and binding.request.run_ref == permit.run_ref,
            "RUNTIME_AUTHORITY_CHANGED",
        )
        require(binding.request.permit_ref == permit.permit_ref, "RUNTIME_PERMIT_CHANGED")
        require(
            binding.backend.helper_sha256 == self.host.helper_sha256
            and binding.backend.binary_sha256 == self.host.bubblewrap_sha256,
            "BACKEND_PINS_CHANGED",
        )
        require(binding.interpreter == self.host.interpreter, "INTERPRETER_PROJECTION_CHANGED")
        if validity == "VALID":
            require(result.evidence.environment is not None, "ENVIRONMENT_INVENTORY_MISSING")
        require(
            result.evidence.non_actions.preparation_network == "NONE",
            "PREPARATION_NETWORK_FORBIDDEN",
        )

    async def run(self, transport: McpTransport) -> dict[str, object]:
        self.compose(transport)
        try:
            await transport.connect()
            await CapabilityRegistrationClient(transport, self.registry).refresh_node(
                self.args.node_id
            )
            admission = (
                self.admission.admit(self.request)
                if self.old is None
                else self.admission.current_admission(self.old.selection.preparation_ref)
            )
            require(
                admission and admission.permit and admission.current_applicable,
                "CURRENT_PREPARATION_AUTHORITY_REQUIRED",
            )
            assert admission and admission.permit
            permit, ref = admission.permit, admission.attempt.preparation_ref
            require(
                permit.not_before <= datetime.now(UTC) < permit.expires_at,
                "PERMIT_EXPIRED_OR_NOT_YET_VALID",
            )
            selection = Selection(request=self.request, preparation_ref=ref)
            if self.old is None:
                write_record(self.root, "e5h-selection.json", selection)
                imported = await self.dispatch.dispatch_and_import(ref)
                pins = permit.spec.source.plan_source
                require(
                    {item.artifact_ref for item in imported}
                    == {pins.raw_artifact_ref, pins.manifest_artifact_ref}
                    and all(item.state.value == "VERIFIED" for item in imported),
                    "EXACT_IMPORT_REQUIRED",
                )
                await transport.disconnect()
                await transport.connect()
                require(
                    await self.dispatch.dispatch_and_import(ref) == imported,
                    "IMPORT_REPLAY_CHANGED",
                )
                source = await self.dispatch.materialize_source(ref)
                prepared = await self.exchange(
                    ref, source, RuntimePreparationOperation.PREPARE_RUNTIME, "h-prepare-1"
                )
                self.validate(prepared, permit, "UNCHECKED")
                require(
                    prepared.current
                    and prepared.current.state.value == "CREATING"
                    and prepared.current.phase.value == "VERIFYING",
                    "CONSTRUCTION_PROMOTED_READINESS",
                )
                replay = await self.exchange(
                    ref, source, RuntimePreparationOperation.PREPARE_RUNTIME, "h-prepare-1"
                )
                require(
                    prepared.construction_sha256 == replay.construction_sha256
                    and prepared.resource_ref == replay.resource_ref,
                    "CONSTRUCTION_REPLAY_CHANGED",
                )
                first = await self.exchange(
                    ref,
                    source,
                    RuntimePreparationOperation.REVALIDATE_RUNTIME,
                    "h-validation-1",
                    prepared,
                )
                self.validate(first, permit, "VALID")
                replay = await self.exchange(
                    ref,
                    source,
                    RuntimePreparationOperation.REVALIDATE_RUNTIME,
                    "h-validation-1",
                    first,
                )
                require(
                    replay.evidence == first.evidence and replay.operation_id == first.operation_id,
                    "VALIDATION_REPLAY_CHANGED",
                )
                checkpoint = Checkpoint(
                    selection=selection, source=source, prepared=prepared, first=first
                )
                result, stage = first, "first-validation"
            else:
                checkpoint = self.old
                source = await self.dispatch.materialize_source(ref)
                require(source == checkpoint.source, "RETAINED_SOURCE_CHANGED")
                status = await self.exchange(
                    ref, source, RuntimePreparationOperation.RUNTIME_STATUS, None, checkpoint.first
                )
                self.validate(status, permit, "UNCHECKED")
                require(
                    status.current
                    and status.current.state.value == "READY"
                    and status.current.phase.value == "PUBLISHED",
                    "RESTART_CHANGED_HISTORICAL_STATE",
                )
                require(
                    status.evidence == checkpoint.first.evidence
                    and status.construction_sha256 == checkpoint.first.construction_sha256,
                    "HISTORICAL_EVIDENCE_CHANGED",
                )
                replay = await self.exchange(
                    ref,
                    source,
                    RuntimePreparationOperation.REVALIDATE_RUNTIME,
                    "h-validation-1",
                    status,
                )
                require(
                    replay.current == status.current and replay.evidence == status.evidence,
                    "HISTORICAL_REPLAY_PROMOTED_VALIDITY",
                )
                result = await self.exchange(
                    ref,
                    source,
                    RuntimePreparationOperation.REVALIDATE_RUNTIME,
                    "h-validation-2",
                    status,
                )
                self.validate(result, permit, "VALID")
                first = checkpoint.first
                require(
                    result.evidence and first.evidence and result.current and first.current,
                    "REVALIDATION_EVIDENCE_REQUIRED",
                )
                assert result.evidence and first.evidence and result.current and first.current
                require(
                    result.resource_ref == first.resource_ref
                    and result.current.binding_sha256 == first.current.binding_sha256
                    and result.construction_sha256 == first.construction_sha256,
                    "RESOURCE_IDENTITY_CHANGED",
                )
                require(
                    result.evidence.environment == first.evidence.environment,
                    "ENVIRONMENT_INVENTORY_CHANGED",
                )
                require(
                    result.current.boot_generation != first.current.boot_generation
                    and result.operation_id != first.operation_id
                    and result.evidence != first.evidence,
                    "FRESH_POST_RESTART_EVIDENCE_REQUIRED",
                )
                old_usage = first.evidence.aggregate_usage.model_dump()
                usage = result.evidence.aggregate_usage.model_dump()
                require(
                    all(usage[k] >= v for k, v in old_usage.items()) and usage != old_usage,
                    "BUDGET_RESET_OR_MISSING_FRESH_CHARGE",
                )
                write_record(self.root, "e5h-restart-status.json", status)
                write_record(self.root, "e5h-second.json", result)
                stage = "post-restart-validation"
            # Ordinary evidence synchronization only, not terminal Result ingestion/E6.
            summary = await transport.synchronize_artifacts(
                CoreArtifactReceiver(self.database, self.storage)
            )
            require(not summary.failed and result.evidence, "EVIDENCE_ARTIFACT_SYNC_FAILED")
            assert result.evidence
            for artifact_ref in result.evidence.evidence_artifact_refs:
                with self.artifacts.open_content(artifact_ref) as stream:
                    payload = stream.read(65537)
                require(len(payload) <= 65536, "EVIDENCE_ARTIFACT_TOO_LARGE")
                parsed = PythonRuntimeEvidence.model_validate_json(payload)
                require(
                    parsed == result.evidence.model_copy(update={"evidence_artifact_refs": ()}),
                    "EVIDENCE_ARTIFACT_MISMATCH",
                )
            with self.database.unit_of_work() as work:
                run = work.runs.get(permit.run_ref)
                require(
                    run and run.status is CapabilityRunStatus.QUEUED, "CORE_RUN_BECAME_TERMINAL"
                )
                require(
                    not work.transport_inbox.list_for_run(permit.run_ref),
                    "UNEXPECTED_TERMINAL_DELIVERY",
                )
            current = self.admission.current_admission(ref)
            require(
                current
                and current.current_applicable
                and current.attempt.lifecycle.value == "DISPATCHED",
                "CORE_PREPARATION_BECAME_TERMINAL",
            )
            assert result.current
            if self.old is None:
                write_record(self.root, "e5h-first-runtime.json", result)
            report = dict(
                schema_version="m20-e5h-core-report@1",
                result="PASS",
                stage=stage,
                selection=selection.model_dump(mode="json"),
                permit_ref=str(permit.permit_ref),
                run_ref=str(permit.run_ref),
                permit_expires_at=permit.expires_at.isoformat(),
                permit_remaining_seconds=max(
                    0, int((permit.expires_at - datetime.now(UTC)).total_seconds())
                ),
                admitted_limits=permit.spec.budgets.model_dump(mode="json"),
                source=source.model_dump(mode="json"),
                runtime=result.model_dump(mode="json"),
                evidence_sha256=python_runtime_evidence_digest(result.evidence),
                core_reopened=self.old is not None,
                historical_replay_did_not_promote=self.old is not None,
                resource_count="verify with paired passive Node report",
                **non_actions(),
            )
            write_record(self.root, f"e5h-{stage}-report.json", report)
            if self.old is None:
                # Last success marker: failed import/sync/assertions cannot turn
                # an incomplete first stage into a resumable H acceptance.
                write_record(self.root, "e5h-first.json", checkpoint)
            return report
        finally:
            await transport.disconnect()


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)
    try:
        if args.check_config or args.node_report:
            from _m20e5h_node import node_report, preflight

            output = (
                asyncio.run(preflight(args)).model_dump(mode="json")
                if args.check_config
                else node_report(args)
            )
        else:
            transport = McpTransport(configuration(args))
            case = CoreCase(args)  # D fixture uses synchronous setup before asyncio.
            try:
                output = asyncio.run(case.run(transport))
            finally:
                case.database.dispose()
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    except AcceptanceFailure as error:
        reason = str(error)
    except TransportError as error:
        reason = error.code
    except PreparationDispatchError as error:
        # Code only, no carrier/server exception strings or headers.
        reason = (
            error.code
            if error.code.isupper() and error.code.replace("_", "").isalnum()
            else "PREPARATION_REJECTED"
        )
    except Exception as error:
        # Includes tool trust/provenance/validation/I/O errors. No traceback or raw
        # exception text (which could contain bearer credentials) is operator output.
        failure = getattr(error, "failure", None)
        if isinstance(failure, PythonRuntimeFailure):
            stage = getattr(error, "stage", None)
            probe = getattr(error, "probe", None)
            print(
                json.dumps(
                    dict(
                        result="FAIL",
                        reason=failure.reason_code.value,
                        runtime_reason=None
                        if failure.runtime_reason is None
                        else failure.runtime_reason.value,
                        stage=stage.value if isinstance(stage, Enum) else None,
                        probe=probe.value if isinstance(probe, Enum) else None,
                        execution_authorized=False,
                    )
                )
            )
            return 1
        reason = "HOST_OR_CONFIGURATION_OR_RUNTIME_FAILURE"
    # Failure is not proof of source integrity, absence of execution or a
    # particular observed lifecycle. Only successful assertions report those.
    print(json.dumps(dict(result="FAIL", reason=reason, execution_authorized=False)))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
