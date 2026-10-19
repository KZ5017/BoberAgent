"""Kali-only H preflight and passive evidence collection; no Core or transport."""

import argparse
import asyncio
import platform
from pathlib import Path
from uuid import uuid4

from _m20e5h_support import (
    PreflightRecord,
    Record,
    fresh_directory,
    non_actions,
    read_record,
    require,
    write_record,
)
from boberagent_contracts import ConfinementFeature, DomainRef, PythonProviderOperation, ResourceRef
from boberagent_execution_node import ExecutionNode, NodeConfiguration
from boberagent_execution_node.config import ToolConfiguration
from boberagent_execution_node.identity import NodeIdentity
from boberagent_execution_node.persistence import RuntimeStore
from boberagent_execution_node.persistence.database import RuntimeDatabase
from boberagent_execution_node.persistence.orm import (
    PreparationMaterializationRow,
    RuntimeConfinementRow,
)
from boberagent_execution_node.preparation.environment_storage import EnvironmentStorage
from boberagent_execution_node.preparation.materializer import (
    MaterializedTree,
    parse_manifest,
    verify_published,
)
from boberagent_execution_node.preparation.python_distribution import (
    PythonDistributionConfiguration,
    digest_value,
    inventory,
    revalidate,
)
from boberagent_execution_node.preparation.python_environment import PythonEnvironmentRepository
from boberagent_execution_node.preparation.python_provenance import enforcement, validate_identity
from boberagent_execution_node.preparation.python_revalidation import _FIELDS
from boberagent_execution_node.preparation.resource_models import BudgetBalance
from boberagent_execution_node.preparation.resources import PythonResourceRepository
from boberagent_execution_node.preparation.runtime_confinement import LinuxRuntimeConfinementBackend
from boberagent_execution_node.preparation.runtime_confinement_models import (
    ProbeEvidence,
    RuntimeConfinementConfiguration,
)
from boberagent_execution_node.preparation.service import NodePreparationService
from boberagent_transport import MaterializationEvidence
from boberagent_transport.preparation_runtime import PythonRuntimeAccepted
from m20e5c_confinement_smoke_test import _require_helper_filesystem
from sqlalchemy import event, select
from sqlalchemy.engine.interfaces import DBAPIConnection


class LedgerSnapshot(Record):
    node_id: str
    resource_ref: ResourceRef
    binding_sha256: str
    construction_sha256: str
    environment_inventory_sha256: str
    budget: tuple[BudgetBalance, ...]


def probe_summary(probe: ProbeEvidence) -> dict[str, object]:
    # No raw stdout/stderr, inherited environment, source bytes or arbitrary errors.
    return {
        name: value
        for name, value in probe.model_dump(mode="json").items()
        if name not in {"stdout_hex", "stderr_hex"}
    }


async def preflight(args: argparse.Namespace) -> PreflightRecord:
    confinement = read_record(args.runtime_confinement_config, RuntimeConfinementConfiguration)
    distribution = read_record(args.python_distribution_config, PythonDistributionConfiguration)
    _require_helper_filesystem(args.trusted_helper)
    fresh_directory(args.node_runtime_directory)
    configuration = NodeConfiguration.for_runtime_directory(
        args.node_runtime_directory,
        tools={
            confinement.helper_tool: ToolConfiguration(executable=str(args.trusted_helper)),
            confinement.bubblewrap_tool: ToolConfiguration(executable=str(args.bubblewrap)),
        },
    )
    node = ExecutionNode(
        configuration,
        runtime_confinement_configuration=confinement,
        python_distribution_configuration=distribution,
    )
    await node.initialize()
    try:
        backend, service = node.runtime_confinement, node.python_runtime_service
        require(
            type(backend) is LinuxRuntimeConfinementBackend and service, "LINUX_BACKEND_REQUIRED"
        )
        assert backend and service and node.identity and node.store
        manifest = inventory(distribution)
        # Same installed-asset gate as E5-E; validate only, never install/repair.
        backend._environment_helper(service.provider.helper_sha256)
        async with asyncio.timeout(210):
            check = await backend.check(tuple(ConfinementFeature))
            probe = await backend.run_identity(distribution, DomainRef(f"h-preflight-{uuid4()}"))
            identity = validate_identity(manifest, probe)
            enforcement(check, probe)
            require(identity.distribution is not None, "DISTRIBUTION_IDENTITY_REQUIRED")
            assert identity.distribution
            require(
                revalidate(distribution, identity.distribution) == manifest, "DISTRIBUTION_DRIFT"
            )
        require(
            not node.store.list_resources() and not node.store.list_sessions(),
            "PREFLIGHT_RESOURCE_CREATED",
        )
        require(not node.store.pending_results(), "PREFLIGHT_TERMINAL_RESULT")
        require(
            not (configuration.workspace_root / "python-environments").exists(),
            "PREFLIGHT_ENVIRONMENT_CREATED",
        )
        parent = confinement.delegated_parent
        result = PreflightRecord(
            node_id=str(node.identity.node_id),
            helper_sha256=confinement.helper_sha256,
            bubblewrap_sha256=confinement.bubblewrap_sha256,
            environment_helper_sha256=service.provider.helper_sha256,
            interpreter=identity,
            kernel=platform.release(),
            profile=check.profile,
            delegation={
                "delegated_parent": str(parent),
                "self_cgroup": Path("/proc/self/cgroup").read_text().strip(),
                **{
                    name: (parent / name).read_text().strip()
                    for name in (
                        "cgroup.type",
                        "cgroup.procs",
                        "cgroup.controllers",
                        "cgroup.subtree_control",
                    )
                },
            },
            probes=[probe_summary(item) for item in (*check.probes, probe)],
            node_configuration={
                **configuration.model_dump(mode="json"),
                "runtime_confinement": confinement.model_dump(mode="json"),
                "python_distribution": distribution.model_dump(mode="json"),
            },
        )
        write_record(args.node_runtime_directory, "e5h-preflight.json", result)
        return result
    finally:
        await node.shutdown()


def _read_only(connection: DBAPIConnection, _record: object) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA query_only=ON")
    finally:
        cursor.close()


def node_report(args: argparse.Namespace) -> dict[str, object]:
    root: Path = args.node_runtime_directory
    require(root.is_absolute() and (root / "runtime.sqlite3").is_file(), "EXISTING_H_NODE_REQUIRED")
    host = read_record(root / "e5h-preflight.json", PreflightRecord)
    identity = read_record(root / "node-identity.json", NodeIdentity)
    require(str(identity.node_id) == host.node_id, "NODE_IDENTITY_CHANGED")
    database = RuntimeDatabase(root / "runtime.sqlite3")
    event.listen(database.migration_engine, "connect", _read_only)
    try:
        store = RuntimeStore(database)
        resources = PythonResourceRepository(
            database, node_id=host.node_id, boot_generation=DomainRef("h-read-only-report")
        )
        ref = ResourceRef(args.resource_ref)
        reserved = resources.load(ref)
        expected = read_record(args.expected_runtime, PythonRuntimeAccepted)
        require(expected.evidence and expected.current, "EXPECTED_CORE_EVIDENCE_REQUIRED")
        assert expected.evidence and expected.current
        require(
            expected.node_id == host.node_id and expected.resource_ref == ref,
            "CORE_RESOURCE_IDENTITY_CONFLICT",
        )
        require(store.get_result(reserved.request.run_ref) is None, "TERMINAL_RESULT_PRESENT")
        require(len(store.list_resources()) == 1, "EXPECTED_EXACTLY_ONE_RESOURCE")
        require(
            not store.list_sessions() and not store.pending_results(), "SESSION_OR_TERMINAL_RESULT"
        )
        require(
            reserved.validity.value == "VALID" and reserved.failure is None,
            "CURRENT_VALID_REQUIRED",
        )
        storage = EnvironmentStorage(root / "workspaces/python-environments")
        retained = PythonEnvironmentRepository(resources, storage).history(ref)
        require(retained is not None, "CONSTRUCTION_HISTORY_REQUIRED")
        assert retained
        require(
            retained.helper_sha256 == host.environment_helper_sha256, "ENVIRONMENT_HELPER_CHANGED"
        )
        require(
            digest_value(retained) == expected.construction_sha256
            and retained.environment == expected.evidence.environment
            and retained.binding == expected.evidence.binding,
            "CORE_NODE_EVIDENCE_MISMATCH",
        )
        require(
            storage.verify_tree(
                storage.resource_directory(ref) / "venv", retained.manifest, retained.binding
            )
            == retained.environment,
            "ENVIRONMENT_DRIFT",
        )
        # Never instantiate NodePreparationService here: its constructor owns
        # startup recovery. Compose its existing PURE E4 verification primitives.
        with database.transaction() as session:
            materialization = session.get(
                PreparationMaterializationRow, str(reserved.request.spec.preparation_ref)
            )
            require(
                materialization is not None and materialization.state == "PUBLISHED",
                "PUBLISHED_SOURCE_REQUIRED",
            )
            assert materialization
            source = MaterializationEvidence.model_validate(materialization.evidence_json)
            rows = tuple(session.scalars(select(RuntimeConfinementRow).limit(129)))
            require(0 < len(rows) <= 128, "PROBE_HISTORY_BOUND_EXCEEDED")
            probes = [ProbeEvidence.model_validate(row.evidence_json) for row in rows]
        pins = reserved.request.spec.source.plan_source
        objects = root / "imported-inputs/objects"
        for sha, size in (
            (pins.raw_sha256, pins.raw_size_bytes),
            (pins.manifest_sha256, reserved.request.spec.source.manifest_size_bytes),
        ):
            path = objects / sha
            require(
                not path.is_symlink() and path.stat().st_size == size,
                "RETAINED_ARTIFACT_SIZE_CHANGED",
            )
            NodePreparationService._verify_file(path, sha, size)
        require(
            source.materialization_id == reserved.request.materialization_id
            and source.tree_sha256 == reserved.request.source_tree_sha256,
            "SOURCE_IDENTITY_CHANGED",
        )
        manifest = parse_manifest(
            (objects / pins.manifest_sha256).read_bytes(),
            pins.raw_sha256,
            pins.raw_size_bytes,
            str(pins.resolved_commit),
            reserved.request.spec.budgets,
        )
        verify_published(
            root
            / "workspaces/preparation-source/published"
            / source.materialization_id.removeprefix("materialization:"),
            manifest,
            MaterializedTree(source.file_count, source.materialized_bytes, source.tree_sha256),
        )
        require(all(item.passed for item in probes), "FAILED_CONFINEMENT_HISTORY")
        # G's acquired-source sentinel is part of the exact reused upstream fixture.
        for probe in probes:
            require(
                b"E5G_ACQUIRED_SOURCE_EXECUTED" not in bytes.fromhex(probe.stdout_hex)
                and b"E5G_ACQUIRED_SOURCE_EXECUTED" not in bytes.fromhex(probe.stderr_hex),
                "SOURCE_EXECUTION_SENTINEL",
            )
        balances = resources.budget(ref)
        usage = expected.evidence.aggregate_usage.model_dump()
        require(
            all(
                item.committed == usage[field]
                for item in balances
                if (field := _FIELDS.get(item.category)) is not None
            ),
            "REPLAY_LEDGER_MISMATCH",
        )
        snapshot = LedgerSnapshot(
            node_id=host.node_id,
            resource_ref=ref,
            binding_sha256=digest_value(retained.binding),
            construction_sha256=digest_value(retained),
            environment_inventory_sha256=retained.environment.inventory_sha256,
            budget=balances,
        )
        if args.stage == "after-revalidation":
            before = read_record(root / "e5h-ledger-before.json", LedgerSnapshot)
            require(
                snapshot.model_dump(exclude={"budget"}) == before.model_dump(exclude={"budget"}),
                "AUDIT_IDENTITY_CHANGED",
            )
            old = {item.category: item for item in before.budget}
            require(
                all(
                    item.limit == old[item.category].limit
                    and item.committed >= old[item.category].committed
                    for item in balances
                ),
                "AUDIT_LEDGER_RESET",
            )
            require(
                any(item.committed > old[item.category].committed for item in balances),
                "FRESH_VALIDATION_NOT_CHARGED",
            )
        else:
            write_record(root, "e5h-ledger-before.json", snapshot)
        operations = resources.operations(ref)
        require(
            sum(
                item.operation is PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT
                for item in operations
            )
            == 1,
            "DUPLICATE_CONSTRUCTION",
        )
        result = dict(
            schema_version="m20-e5h-node-evidence@1",
            result="PASS",
            stage=args.stage,
            node_id=host.node_id,
            resource_ref=str(ref),
            request_sha256=reserved.request_sha256,
            binding_sha256=digest_value(retained.binding),
            construction_sha256=digest_value(retained),
            environment_inventory_sha256=retained.environment.inventory_sha256,
            budget=[item.model_dump(mode="json") for item in balances],
            operations=[
                item.model_dump(mode="json", exclude={"owner_token"}) for item in operations
            ],
            probes=[probe_summary(item) for item in probes],
            source_verified=True,
            environment_verified=True,
            resource_count=1,
            **non_actions(),
        )
        write_record(root, f"e5h-node-{args.stage}.json", result)
        return result
    finally:
        database.close()
