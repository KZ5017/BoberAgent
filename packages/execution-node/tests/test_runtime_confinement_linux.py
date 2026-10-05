"""Opt-in real Linux enforcement. A skip is NOT E5-C acceptance.

Requires the explicitly provisioned delegated parent and pinned built helper.
Never provisions systemd/cgroups, installs tools, or runs acquired source.
"""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from boberagent_contracts import ConfinementFeature, DomainRef
from boberagent_execution_node.config import ToolConfiguration
from boberagent_execution_node.identity import NodeId
from boberagent_execution_node.persistence import RuntimeDatabase
from boberagent_execution_node.persistence.migrations import upgrade_database
from boberagent_execution_node.preparation.runtime_confinement import LinuxRuntimeConfinementBackend
from boberagent_execution_node.preparation.runtime_confinement_models import (
    ClosedProbe,
    RuntimeConfinementConfiguration,
    StopReason,
)
from boberagent_execution_node.tools import ToolRegistry


def test_real_enforcement_all_twelve_features_and_death_cleanup(tmp_path: Path) -> None:
    parent = os.environ.get("BOBERAGENT_E5_CGROUP_PARENT")
    if not parent:
        pytest.skip("opt-in operator delegation not supplied; not enforcement acceptance")
    # An explicitly opted-in but incomplete/broken configuration FAILS, not skips.
    configuration = RuntimeConfinementConfiguration(
        delegated_parent=Path(parent),
        helper_sha256=os.environ["BOBERAGENT_E5_HELPER_SHA256"],
        bubblewrap_sha256=os.environ["BOBERAGENT_E5_BWRAP_SHA256"],
    )
    helper = os.environ["BOBERAGENT_E5_HELPER"]
    bwrap = os.environ.get("BOBERAGENT_E5_BWRAP", "/usr/bin/bwrap")
    database = RuntimeDatabase(tmp_path / "runtime.sqlite3")
    upgrade_database(database)

    async def run() -> None:
        tools = ToolRegistry()
        tools.register(configuration.helper_tool, ToolConfiguration(executable=helper))
        tools.register(configuration.bubblewrap_tool, ToolConfiguration(executable=bwrap))
        await tools.refresh()
        backend = LinuxRuntimeConfinementBackend(
            configuration=configuration,
            node_id=NodeId("node-e5-confinement-test"),
            tools=tools,
            database=database,
            runtime_directory=tmp_path,
            boot_generation=DomainRef(f"boot-{uuid4()}"),
        )
        proof = await backend.check(tuple(ConfinementFeature))
        assert set(proof.features) == set(ConfinementFeature)
        assert len(proof.probes) == 13
        assert all(
            probe.passed and probe.group_empty and probe.attached_before_exec
            for probe in proof.probes
        )
        requester = next(item for item in proof.probes if item.probe is ClosedProbe.REQUESTER_DEATH)
        assert requester.requester_exit_code == -9
        assert requester.stop_reason is StopReason.OWNER_LOST
        assert bytes.fromhex(requester.stdout_hex).startswith(b"DESCENDANTS_STARTED\n")
        supervisor = next(
            item for item in proof.probes if item.probe is ClosedProbe.SUPERVISOR_DEATH
        )
        assert supervisor.stop_reason is StopReason.SUPERVISOR_LOST
        assert not tuple(Path(parent).glob("bober-e5-*"))
        assert await backend.reconcile_owned() == 0

    try:
        asyncio.run(run())
    finally:
        database.close()
