"""Operator-only trusted distribution preflight; never venv/source preparation.

Inventory mode executes nothing. Check mode runs fresh closed confinement probes
and only the fixed identity. It creates no Resource/permit or readiness claim.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from boberagent_contracts import ConfinementFeature, DomainRef
from boberagent_contracts.plan_canonical import canonical_json, canonical_value
from boberagent_execution_node import ExecutionNode, NodeConfiguration
from boberagent_execution_node.config import ToolConfiguration
from boberagent_execution_node.preparation.python_distribution import (
    ProvenanceFailure,
    PythonDistributionConfiguration,
    digest_value,
    inventory,
    revalidate,
)
from boberagent_execution_node.preparation.python_provenance import enforcement, validate_identity
from boberagent_execution_node.preparation.runtime_confinement import RuntimeConfinementUnavailable
from boberagent_execution_node.preparation.runtime_confinement_models import (
    RuntimeConfinementConfiguration,
)
from m20e5c_confinement_smoke_test import _failure_json, _require_helper_filesystem


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inventory-only", action="store_true")
    mode.add_argument("--check-provenance", action="store_true")
    parser.add_argument("--distribution-root", required=True, type=Path)
    parser.add_argument("--system-library-root", required=True, type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--interpreter-sha256")
    parser.add_argument("--node-runtime-directory", type=Path)
    parser.add_argument("--delegated-cgroup-parent", type=Path)
    parser.add_argument("--trusted-helper", type=Path)
    parser.add_argument("--helper-sha256")
    parser.add_argument("--bubblewrap", type=Path, default=Path("/usr/bin/bwrap"))
    parser.add_argument("--bubblewrap-sha256")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    if bool(args.manifest_sha256) != bool(args.interpreter_sha256):
        raise ValueError("both distribution pins required together")
    if not args.inventory_only and not (args.manifest_sha256 and args.interpreter_sha256):
        raise ValueError("reviewed distribution pins required")
    distribution = PythonDistributionConfiguration(
        distribution_root=args.distribution_root,
        system_library_root=args.system_library_root,
        expected_manifest_sha256=args.manifest_sha256 or "0" * 64,
        expected_interpreter_sha256=args.interpreter_sha256 or "0" * 64,
    )
    manifest = inventory(
        distribution, verify_pins=not args.inventory_only or bool(args.manifest_sha256)
    )
    if args.inventory_only:
        print(
            json.dumps(
                {
                    "result": "INVENTORY_ONLY_NOT_AUTHORITY",
                    "manifest_sha256": manifest.digest,
                    "interpreter_sha256": manifest.interpreter_sha256,
                    "root_binding_sha256": manifest.root_binding_sha256,
                    "entries": len(manifest.entries) + len(manifest.support_entries),
                    "manifest_version": manifest.schema_version,
                    "projection": manifest.projection.model_dump(mode="json"),
                    "excluded_entries": len(manifest.excluded_entries),
                    "runtime": "UNAVAILABLE",
                    "ready": False,
                }
            )
        )
        return 0
    root = args.node_runtime_directory
    if root is None or not root.is_absolute() or args.trusted_helper is None:
        raise ValueError("explicit dedicated runtime and trusted helper required")
    _require_helper_filesystem(args.trusted_helper)
    marker = root / "e5d-provenance-only"
    if (root / "runtime.sqlite3").exists() and not marker.is_file():
        raise ValueError("dedicated provenance-only runtime required")
    root.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        marker.write_text("m20-e5-python-distribution@1\n", encoding="ascii")
    configuration = RuntimeConfinementConfiguration(
        delegated_parent=args.delegated_cgroup_parent,
        helper_sha256=args.helper_sha256,
        bubblewrap_sha256=args.bubblewrap_sha256,
    )
    node = ExecutionNode(
        NodeConfiguration.for_runtime_directory(
            root,
            tools={
                configuration.helper_tool: ToolConfiguration(executable=str(args.trusted_helper)),
                configuration.bubblewrap_tool: ToolConfiguration(executable=str(args.bubblewrap)),
            },
        ),
        runtime_confinement_configuration=configuration,
    )
    await node.initialize()
    try:
        backend = node.runtime_confinement
        assert backend is not None
        async with asyncio.timeout(210):
            check = await backend.check(tuple(ConfinementFeature))
            operation_id = DomainRef(f"python-identity-{uuid4()}")
            probe = await backend.run_identity(distribution, operation_id)
            identity = validate_identity(manifest, probe)
            assert identity.distribution is not None
            proof = enforcement(check, probe)
            assert revalidate(distribution, identity.distribution) == manifest
        # A host preflight has no admitted preparation/Resource. Do not manufacture
        # an E5-B grant or a Resource-bound PythonRuntimeEvidence dossier for it.
        # Retain the same typed interpreter and enforcement facts plus journal refs.
        dossier = {
            "interpreter": identity,
            "enforcement": proof,
            "confinement_check": check,
            "identity_operation": probe,
            "manifest": manifest,
        }
        encoded = canonical_json(canonical_value(dossier)) + "\n"
        fd = os.open(
            root / f"{operation_id}.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "operation_id": str(operation_id),
                    "version": identity.summary.python_version,
                    "implementation": identity.implementation,
                    "architecture": identity.architecture,
                    "platform": identity.summary.platform,
                    "interpreter_sha256": manifest.interpreter_sha256,
                    "manifest_sha256": manifest.digest,
                    "root_binding_sha256": manifest.root_binding_sha256,
                    "manifest_version": manifest.schema_version,
                    "projection": manifest.projection.model_dump(mode="json"),
                    "evidence_sha256": digest_value(dossier),
                    "revalidation": "PASS",
                    "resource_created": False,
                    "runtime": "UNAVAILABLE",
                    "ready": False,
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
    except ProvenanceFailure as error:
        print(
            json.dumps(
                {
                    "result": "FAIL",
                    "reason": error.failure.reason_code.value,
                    "detail": str(error),
                    "stage": error.stage,
                    "runtime": "UNAVAILABLE",
                    "ready": False,
                }
            )
        )
    except (ValueError, OSError, TimeoutError):
        print(
            json.dumps(
                {
                    "result": "FAIL",
                    "reason": "PROVENANCE_PREFLIGHT_INVALID",
                    "runtime": "UNAVAILABLE",
                    "ready": False,
                }
            )
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
