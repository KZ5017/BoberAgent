"""Opt-in LOCAL Kali E5-E construction under an existing current E3/E4 admission.

Stop the Node using this DB before running. This harness issues NO permit, edits
NO authority/budget, accesses NO source bytes, and adds NO E5 transport wiring.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from boberagent_contracts import (
    DomainRef,
    PreparationPermit,
    PythonBackendIdentity,
    PythonProjectedDistributionIdentity,
    PythonProviderOperation,
    PythonProviderPhase,
    PythonResourceState,
    PythonRuntimeAuthorityProjection,
    PythonRuntimeProfileIdentity,
    PythonRuntimeRequestBinding,
    PythonRuntimeValidity,
    preparation_permit_digest,
)
from boberagent_execution_node import ExecutionNode, NodeConfiguration
from boberagent_execution_node.config import ToolConfiguration
from boberagent_execution_node.persistence.orm import (
    PreparationAuthorityRow,
    PreparationMaterializationRow,
)
from boberagent_execution_node.preparation.python_distribution import (
    ProvenanceFailure,
    PythonDistributionConfiguration,
    digest_value,
)
from boberagent_execution_node.preparation.python_environment import (
    EnvironmentFailure,
    PythonEnvironmentProvider,
)
from boberagent_execution_node.preparation.python_provenance import (
    PythonProvenanceRepository,
    inspect_owned_interpreter,
)
from boberagent_execution_node.preparation.resources import ResourceOwnershipError
from boberagent_execution_node.preparation.runtime_confinement import RuntimeConfinementUnavailable
from boberagent_execution_node.preparation.runtime_confinement_models import (
    RuntimeConfinementConfiguration,
)
from boberagent_transport.preparation_materialization import MaterializationEvidence
from m20e5c_confinement_smoke_test import _failure_json, _require_helper_filesystem


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--construct-empty-environment", action="store_true", required=True)
    parser.add_argument("--node-runtime-directory", required=True, type=Path)
    parser.add_argument("--permit-ref", required=True)
    parser.add_argument("--distribution-root", required=True, type=Path)
    parser.add_argument("--system-library-root", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--interpreter-sha256", required=True)
    parser.add_argument("--delegated-cgroup-parent", required=True, type=Path)
    parser.add_argument("--trusted-helper", required=True, type=Path)
    parser.add_argument("--helper-sha256", required=True)
    parser.add_argument("--bubblewrap", type=Path, default=Path("/usr/bin/bwrap"))
    parser.add_argument("--bubblewrap-sha256", required=True)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    root = args.node_runtime_directory
    if not root.is_absolute() or not (root / "runtime.sqlite3").is_file():
        raise ValueError("existing explicit Node runtime with current E4 admission required")
    _require_helper_filesystem(args.trusted_helper)
    confinement = RuntimeConfinementConfiguration(
        delegated_parent=args.delegated_cgroup_parent,
        helper_sha256=args.helper_sha256,
        bubblewrap_sha256=args.bubblewrap_sha256,
    )
    node = ExecutionNode(
        NodeConfiguration.for_runtime_directory(
            root,
            tools={
                confinement.helper_tool: ToolConfiguration(executable=str(args.trusted_helper)),
                confinement.bubblewrap_tool: ToolConfiguration(executable=str(args.bubblewrap)),
            },
        ),
        runtime_confinement_configuration=confinement,
    )
    await node.initialize()
    try:
        database, resources, repository, backend = (
            node.database,
            node.python_resources,
            node.python_environments,
            node.runtime_confinement,
        )
        assert (
            database is not None
            and resources is not None
            and repository is not None
            and backend is not None
        )
        with database.transaction() as session:
            authority = session.get(PreparationAuthorityRow, args.permit_ref)
            if authority is None or authority.principal_id != "boberagent-core":
                raise ValueError("existing authenticated Core admission required")
            permit = PreparationPermit.model_validate(authority.permit_json)
            materialization = session.get(
                PreparationMaterializationRow, str(permit.spec.preparation_ref)
            )
            if (
                materialization is None
                or materialization.state != "PUBLISHED"
                or materialization.evidence_json is None
            ):
                raise ValueError("published E4 metadata required")
            e4 = MaterializationEvidence.model_validate(materialization.evidence_json)
        distribution = PythonDistributionConfiguration(
            distribution_root=args.distribution_root,
            system_library_root=args.system_library_root,
            expected_manifest_sha256=args.manifest_sha256,
            expected_interpreter_sha256=args.interpreter_sha256,
        )
        provider = PythonEnvironmentProvider(
            distribution=distribution,
            backend=backend,
            backend_identity=PythonBackendIdentity(
                backend_id="linux-bwrap-cgroup",
                backend_version="1",
                profile_id="m20-e5-linux-bwrap-cgroup",
                profile_version="1",
                profile_sha256=digest_value({"profile": "m20-e5-linux-bwrap-cgroup@1"}),
                binary_sha256=args.bubblewrap_sha256,
                binary_version="0.11.0",
                helper_sha256=args.helper_sha256,
            ),
            repository=repository,
        )
        # Explicitly installed provider asset; fail with closed diagnostics before
        # any Resource claim/budget spend. Never chmod/install from this harness.
        backend._environment_helper(provider.helper_sha256)
        request = PythonRuntimeRequestBinding(
            schema_version="python-runtime-request-binding-v1",
            spec=permit.spec,
            permit_ref=permit.permit_ref,
            permit_sha256=preparation_permit_digest(permit),
            run_ref=permit.run_ref,
            materialization_id=e4.materialization_id,
            source_tree_sha256=e4.tree_sha256,
            entrypoint_sha256=permit.spec.entrypoint.entry_sha256,
            profile=PythonRuntimeProfileIdentity(
                profile_id=permit.spec.profile.profile_id,
                profile_version=permit.spec.profile.profile_version,
                profile_sha256=permit.spec.profile_sha256,
                runtime_provider="python-stdlib@1",
                construction_version="python-stdlib@1",
                layout_version="m20-e5-python-layout@1",
            ),
        )
        reservation = resources.reserve(
            PythonRuntimeAuthorityProjection(permit=permit, binding=request),
            principal_id="boberagent-core",
        )
        identity = provider.backend_identity
        provenance = PythonProvenanceRepository(resources)
        if not provenance.history(reservation.resource_ref):
            inspect = resources.claim(
                reservation.resource_ref,
                operation_id=DomainRef(f"inspect-e5e-{uuid4()}"),
                operation=PythonProviderOperation.INSPECT_INTERPRETER,
                owner_token=DomainRef(f"owner-{uuid4()}"),
                lease_seconds=300,
                principal_id="boberagent-core",
            )
            await inspect_owned_interpreter(distribution, backend, identity, provenance, inspect)
        evidence = repository.history(reservation.resource_ref)
        replay = evidence is not None
        if evidence is None:
            claim = resources.claim(
                reservation.resource_ref,
                operation_id=DomainRef(f"construct-e5e-{uuid4()}"),
                operation=PythonProviderOperation.CREATE_EMPTY_ENVIRONMENT,
                owner_token=DomainRef(f"owner-{uuid4()}"),
                lease_seconds=360,
                principal_id="boberagent-core",
            )
            evidence = await provider.create_empty_environment(claim)
        assert repository.inspect_retained(reservation.resource_ref) == evidence
        assert repository.reconcile_retained() == 0
        current = resources.load(reservation.resource_ref)
        if (current.state, current.phase, current.validity) != (
            PythonResourceState.CREATING,
            PythonProviderPhase.VERIFYING,
            PythonRuntimeValidity.UNCHECKED,
        ):
            raise ValueError("retained evidence does not imply current construction success")
        selected_distribution = evidence.binding.interpreter.distribution
        assert isinstance(selected_distribution, PythonProjectedDistributionIdentity)
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "resource_ref": str(reservation.resource_ref),
                    "operation_id": str(evidence.operation_id),
                    "evidence_sha256": digest_value(evidence),
                    "manifest_sha256": args.manifest_sha256,
                    "projection_sha256": selected_distribution.projection.projection_sha256,
                    "environment_inventory_sha256": evidence.environment.inventory_sha256,
                    "committed_environment_writes": evidence.committed_write_bytes,
                    "committed_environment_entries": evidence.committed_file_count,
                    "descendants_empty": evidence.construction.group_empty
                    and evidence.verification.group_empty,
                    "state": current.state.value,
                    "phase": current.phase.value,
                    "validity": current.validity.value,
                    "runtime": "UNAVAILABLE",
                    "inspection": "PASSIVE_RETAINED_HISTORY" if replay else "FRESH_CONSTRUCTION",
                    "ready": False,
                    "execution_authorized": False,
                    "checked_at": datetime.now(UTC).isoformat(),
                }
            )
        )
        return 0
    finally:
        await node.shutdown()


def main() -> int:
    try:
        return asyncio.run(run(arguments()))
    except RuntimeConfinementUnavailable as error:
        print(_failure_json(error))
    except (EnvironmentFailure, ProvenanceFailure, ResourceOwnershipError) as error:
        reason = (
            error.code if isinstance(error, ResourceOwnershipError) else error.failure.reason_code
        )
        print(
            json.dumps(
                {
                    "result": "FAIL",
                    "reason": reason.value,
                    "ready": False,
                    "execution_authorized": False,
                }
            )
        )
    except (ValueError, OSError, TimeoutError):
        print(
            json.dumps(
                {
                    "result": "FAIL",
                    "reason": "EMPTY_ENVIRONMENT_PREREQUISITE_INVALID",
                    "ready": False,
                    "execution_authorized": False,
                }
            )
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
