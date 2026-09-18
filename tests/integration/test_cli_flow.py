"""CLI-to-Workflow integration through the existing in-memory transport and Node runtime."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from io import StringIO
from pathlib import Path

from boberagent_cli.composition import (
    RemoteNodeConfiguration,
    WorkflowCommandSession,
)
from boberagent_cli.main import run
from boberagent_core import (
    CapabilityRegistrationClient,
    CapabilityRegistry,
    CapabilityRouter,
    CoreDatabase,
    CoreTransportClient,
    CoreTransportReceiver,
    ResultIngestionService,
    WorkflowService,
)
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_transport import InMemoryTransport
from transport_test_capability import capability_manifest, reset_control


class InMemoryWorkflowSession:
    def __init__(
        self,
        workflows: WorkflowService,
        client: CoreTransportClient,
        node_id: str,
    ) -> None:
        self.workflows = workflows
        self._client = client
        self._node_id = node_id

    async def receive_pending(self) -> int:
        count = await self._client.flush_node(self._node_id)
        for _ in range(count):
            await self._client.receive_one()
        return count


class InMemoryWorkflowSessionFactory:
    def __init__(self, configuration: NodeConfiguration) -> None:
        self._configuration = configuration

    @asynccontextmanager
    async def __call__(
        self,
        database: CoreDatabase,
        remote: RemoteNodeConfiguration,
    ) -> AsyncIterator[WorkflowCommandSession]:
        del remote
        node = ExecutionNode(self._configuration)
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport = InMemoryTransport(queue_capacity=30)
        transport.register_node(endpoint)
        registry = CapabilityRegistry(database)
        registration = CapabilityRegistrationClient(transport, registry)
        ingestion = ResultIngestionService(database)
        receiver = CoreTransportReceiver(database, result_ingestion=ingestion)
        client = CoreTransportClient(transport, receiver)
        await transport.connect()
        await registration.refresh_node(endpoint.node_id)
        session = InMemoryWorkflowSession(
            WorkflowService(database, CapabilityRouter(registry, transport)),
            client,
            endpoint.node_id,
        )
        try:
            yield session
            await transport.wait_for_idle()
        finally:
            await transport.disconnect()
            await node.shutdown()


def _invoke(
    database_path: Path,
    arguments: Sequence[str],
    *,
    sessions: InMemoryWorkflowSessionFactory,
    environment: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    code = run(
        ["--database", str(database_path), *arguments],
        stdout=stdout,
        stderr=stderr,
        environment={} if environment is None else environment,
        workflow_sessions=sessions,
    )
    return code, stdout.getvalue(), stderr.getvalue()


def _configuration(tmp_path: Path) -> NodeConfiguration:
    capability_path = tmp_path / "capabilities"
    capability_path.mkdir()
    (capability_path / "capability.json").write_text(
        json.dumps(capability_manifest(), indent=2), encoding="utf-8"
    )
    return NodeConfiguration.for_runtime_directory(
        tmp_path / "node-runtime",
        capability_paths=(capability_path,),
        configured_node_id="node-cli-in-memory",
    )


def test_cli_mission_asset_workflow_result_and_completion(tmp_path: Path) -> None:
    reset_control()
    database_path = tmp_path / "core.sqlite3"
    sessions = InMemoryWorkflowSessionFactory(_configuration(tmp_path))
    assert _invoke(database_path, ["core", "init"], sessions=sessions)[0] == 0
    assert (
        _invoke(
            database_path,
            ["mission", "create", "--mission-ref", "mission-cli-integration"],
            sessions=sessions,
        )[0]
        == 0
    )
    assert (
        _invoke(
            database_path,
            [
                "asset",
                "add",
                "--asset-ref",
                "asset-cli-integration",
                "--mission",
                "mission-cli-integration",
                "--address",
                "192.0.2.80",
            ],
            sessions=sessions,
        )[0]
        == 0
    )
    definition = tmp_path / "workflow.json"
    definition.write_text(
        json.dumps(
            {
                "definition_id": "procedure.test.cli_integration",
                "version": "1",
                "steps": [
                    {
                        "step_id": "synthetic",
                        "capability_id": "test.transport_synthetic",
                        "operation": "execute",
                        "inputs": {
                            "asset_ref": "asset-cli-integration",
                            "message": "CLI integration payload",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    remote = [
        "--node-url",
        "http://localhost:8000/mcp",
        "--node-id",
        "node-cli-in-memory",
        "--json",
    ]
    environment = {"BOBERAGENT_MCP_BEARER_TOKEN": "integration-secret"}
    code, output, error = _invoke(
        database_path,
        [
            *remote,
            "workflow",
            "start",
            "--mission",
            "mission-cli-integration",
            "--definition",
            str(definition),
            "--workflow-ref",
            "workflow-cli-integration",
        ],
        sessions=sessions,
        environment=environment,
    )
    assert code == 0 and error == ""
    started = json.loads(output)
    assert started["steps"][0]["status"] == "ACTIVE"
    run_ref = started["steps"][0]["capability_run_ref"]
    assert "integration-secret" not in output

    code, output, error = _invoke(
        database_path,
        [*remote, "workflow", "advance", "workflow-cli-integration"],
        sessions=sessions,
        environment=environment,
    )
    assert code == 0 and error == ""
    assert json.loads(output)["run"]["status"] == "COMPLETED"

    code, output, error = _invoke(
        database_path,
        ["--json", "run", "show", run_ref],
        sessions=sessions,
    )
    assert code == 0 and error == ""
    inspected = json.loads(output)
    assert inspected["run"]["status"] == "COMPLETED"
    assert inspected["result_ingestion"]["result"]["outcome"]["category"] == "SUCCESS"
