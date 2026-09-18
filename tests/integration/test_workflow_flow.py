"""M11 production Capability orchestration through the durable Workflow Engine."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from boberagent_contracts import AssetRef, MissionRef, WorkflowRunRef
from boberagent_core import (
    Asset,
    CapabilityRegistrationClient,
    CapabilityRegistry,
    CapabilityRouter,
    CoreDatabase,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    Mission,
    ResultIngestionService,
    WorkflowDefinition,
    WorkflowService,
    WorkflowStatus,
    WorkflowStepDefinition,
    WorkflowStepStatus,
    WorkflowStepSuccessPolicy,
    upgrade_database,
)
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
    ToolConfiguration,
)
from boberagent_transport import InMemoryTransport

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_ROOT = REPOSITORY_ROOT / "capabilities" / "network-service-discovery"
SHIM_FIXTURE = CAPABILITY_ROOT / "tests" / "fixtures" / "nmap_shim.py"
NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
MISSION_REF = MissionRef("mission-workflow-network-discovery")
ASSET_REF = AssetRef("asset-workflow-network-discovery")


def _make_nmap_shim(tmp_path: Path) -> Path:
    target = tmp_path / "nmap-workflow-shim"
    source_lines = SHIM_FIXTURE.read_text(encoding="utf-8").splitlines()
    source_lines[0] = f"#!{sys.executable}"
    target.write_text("\n".join(source_lines) + "\n", encoding="utf-8")
    target.chmod(0o700)
    return target


def test_network_service_discovery_runs_through_workflow_engine(tmp_path: Path) -> None:
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(database)
    with database.unit_of_work() as work:
        work.missions.add(
            Mission(
                mission_ref=MISSION_REF,
                status="ACTIVE",
                created_at=NOW,
                name="Workflow network discovery",
            )
        )
        work.assets.add(
            Asset(
                asset_ref=ASSET_REF,
                mission_ref=MISSION_REF,
                kind="host",
                primary_address="192.0.2.25",
                created_at=NOW,
            )
        )

    transport = InMemoryTransport(queue_capacity=30)
    registry = CapabilityRegistry(database)
    registration = CapabilityRegistrationClient(transport, registry)
    router = CapabilityRouter(registry, transport)
    ingestion = ResultIngestionService(database)
    receiver = CoreTransportReceiver(database, result_ingestion=ingestion)
    receiver_client = CoreTransportClient(transport, receiver)
    workflows = WorkflowService(database, router)
    definition = WorkflowDefinition(
        definition_id="procedure.network.service_discovery_baseline",
        version="1",
        steps=(
            WorkflowStepDefinition(
                step_id="discover-services",
                capability_id="network.service_discovery",
                operation="discover",
                inputs={
                    "asset_ref": str(ASSET_REF),
                    "profile": "quick",
                    "timeout_seconds": 10,
                },
                success_policy=WorkflowStepSuccessPolicy.SUCCESS_OR_NEGATIVE,
            ),
        ),
    )

    async def scenario() -> None:
        shim = _make_nmap_shim(tmp_path)
        node = ExecutionNode(
            NodeConfiguration.for_runtime_directory(
                tmp_path / "node",
                capability_paths=(CAPABILITY_ROOT,),
                tools={"nmap": ToolConfiguration(executable=str(shim))},
                configured_node_id="node-workflow-integration",
            )
        )
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport.register_node(endpoint)
        await transport.connect()
        await registration.refresh_node(endpoint.node_id)

        workflow_ref = WorkflowRunRef("workflow-network-discovery")
        active = await workflows.start(
            definition,
            MISSION_REF,
            workflow_run_ref=workflow_ref,
        )
        assert active.run.status is WorkflowStatus.RUNNING
        assert active.steps[0].status is WorkflowStepStatus.ACTIVE
        run_ref = active.steps[0].capability_run_ref
        assert run_ref is not None

        await asyncio.wait_for(transport.wait_for_idle(), timeout=5)
        outbound = await receiver_client.flush_node(endpoint.node_id)
        assert outbound > 0
        for _ in range(outbound):
            await receiver_client.receive_one()

        completed = await workflows.advance(workflow_ref)
        assert completed.run.status is WorkflowStatus.COMPLETED
        assert completed.steps[0].status is WorkflowStepStatus.COMPLETED
        assert completed.steps[0].capability_run_ref == run_ref
        result = ingestion.get_ingestion(run_ref)
        assert result is not None
        assert result.result.observations
        assert {observation.type for observation in result.result.observations} == {
            "network.service"
        }
        assert registry.routing_decision_for_run(run_ref) is not None
        with database.unit_of_work() as work:
            services = work.services.list_for_asset(ASSET_REF)
        assert {service.port for service in services} == {22, 80}

        await transport.disconnect()
        await node.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        database.dispose()
