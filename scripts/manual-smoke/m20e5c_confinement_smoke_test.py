"""Operator-only bounded Linux confinement proof; no Python runtime or acquired source.

Run inside the explicitly operator-provisioned delegation service. No host configuration,
compiler, installer, Core/MCP traffic or target contact is performed by this harness.
"""

import argparse
import asyncio
import hashlib
import json
import stat
from pathlib import Path

from boberagent_contracts import ConfinementFeature
from boberagent_execution_node import ExecutionNode, NodeConfiguration
from boberagent_execution_node.config import ToolConfiguration
from boberagent_execution_node.preparation.runtime_confinement import (
    RuntimeConfinementUnavailable,
)
from boberagent_execution_node.preparation.runtime_confinement_models import (
    ConfinementFailureStage,
    RuntimeConfinementConfiguration,
)


def _require_helper_filesystem(path: Path) -> None:
    """Read-only operator prerequisite; never replace or weaken _trusted_tool()."""
    try:
        mode = path.lstat().st_mode
        if not path.is_absolute() or not stat.S_ISREG(mode) or mode & 0o6022 or not mode & 0o111:
            raise ValueError("untrusted helper mode")
    except (OSError, ValueError):
        raise RuntimeConfinementUnavailable(
            stage=ConfinementFailureStage.HELPER_FILE_MODE
        ) from None
    try:
        for directory in path.parents:
            mode = directory.lstat().st_mode
            # No sticky-bit exception for this explicit installation prerequisite.
            if not stat.S_ISDIR(mode) or mode & 0o022:
                raise ValueError("untrusted helper parent")
    except (OSError, ValueError):
        raise RuntimeConfinementUnavailable(
            stage=ConfinementFailureStage.HELPER_PARENT_TRUST
        ) from None


def _failure_json(error: RuntimeConfinementUnavailable) -> str:
    return json.dumps(
        {
            "profile": "m20-e5-linux-bwrap-cgroup@1",
            "result": "FAIL",
            "reason": str(error),
            "probe": error.probe.value if error.probe else None,
            "stage": error.stage.value if error.stage else None,
            "runtime": "UNAVAILABLE",
            "ready": False,
        }
    )


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-confinement", required=True, action="store_true")
    parser.add_argument("--node-runtime-directory", required=True, type=Path)
    parser.add_argument("--delegated-cgroup-parent", required=True, type=Path)
    parser.add_argument("--trusted-helper", required=True, type=Path)
    parser.add_argument("--helper-sha256", required=True)
    parser.add_argument("--bubblewrap", default=Path("/usr/bin/bwrap"), type=Path)
    parser.add_argument("--bubblewrap-sha256", required=True)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    if not args.node_runtime_directory.is_absolute():
        raise ValueError("explicit absolute Node runtime directory required")
    _require_helper_filesystem(args.trusted_helper)
    root = args.node_runtime_directory
    marker = root / "e5c-confinement-only"
    if (root / "runtime.sqlite3").exists() and not marker.is_file():
        raise ValueError("use a dedicated confinement-only runtime, not a live Node database")
    root.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        marker.write_text("m20-e5-linux-bwrap-cgroup@1\n", encoding="ascii")
    configuration = RuntimeConfinementConfiguration(
        delegated_parent=args.delegated_cgroup_parent,
        helper_sha256=args.helper_sha256,
        bubblewrap_sha256=args.bubblewrap_sha256,
    )
    node = ExecutionNode(
        NodeConfiguration.for_runtime_directory(
            args.node_runtime_directory,
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
        try:
            result = await backend.check(tuple(ConfinementFeature))
        except RuntimeConfinementUnavailable as error:
            print(_failure_json(error))
            return 1
        for probe in result.probes:
            # Never dump raw environment or captured process stderr/host paths.
            print(
                json.dumps(
                    {
                        "probe": probe.probe.value,
                        "passed": probe.passed,
                        "attached_before_exec": probe.attached_before_exec,
                        "group_empty": probe.group_empty,
                        "pids_events": probe.pids_events,
                        "oom_events": probe.oom_events,
                        "memory_peak": probe.memory_peak,
                        "stop": probe.stop_reason.value,
                        "requester_exit_code": probe.requester_exit_code,
                    }
                )
            )
        encoded = result.model_dump_json().encode()
        print(
            json.dumps(
                {
                    "profile": result.profile,
                    "features": [feature.value for feature in result.features],
                    "probe_count": len(result.probes),
                    "evidence_sha256": hashlib.sha256(encoded).hexdigest(),
                    "result": "PASS",
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
        return 1
    except (ValueError, OSError) as error:
        print(
            json.dumps(
                {
                    "result": "FAIL",
                    "reason": type(error).__name__,
                    "runtime": "UNAVAILABLE",
                    "ready": False,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
