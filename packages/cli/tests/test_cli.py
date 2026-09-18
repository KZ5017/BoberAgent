"""Focused operator CLI parsing, persistence, output, and service-delegation tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from boberagent_cli.composition import (
    RemoteNodeConfiguration,
    WorkflowCommandSession,
    WorkflowSessionFactory,
)
from boberagent_cli.main import run
from boberagent_contracts import (
    CONTRACT_VERSION,
    AssetRef,
    CapabilityDefinition,
    CapabilityOutcome,
    CapabilityOutcomeCategory,
    CapabilityResult,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    ExecutionCharacteristics,
    ExecutionDuration,
    ExecutionInteraction,
    InteractionSurfaceDeclaration,
    MissionRef,
    Observation,
    ObservationRef,
    OperationDefinition,
    ResultObjectType,
    RetrySemantics,
    SchemaDeclaration,
    SideEffectCategory,
    SideEffectDeclaration,
    SideEffectLevel,
)
from boberagent_core import (
    Asset,
    CapabilityRegistry,
    CapabilityRouter,
    CoreDatabase,
    CorePersistence,
    DatabaseConfig,
    Mission,
    ResultIngestionService,
    WorkflowService,
    current_revision,
)
from boberagent_transport import (
    AdvertisedCapabilityStatus,
    CapabilityStatusAdvertisement,
    CapabilityTransport,
    DeliveryAcknowledgement,
    InvocationDelivery,
    NodeAdvertisement,
    TransportDisconnected,
    TransportFailure,
    TransportMessageId,
    invocation_message_id,
)

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


class RecordingTransport(CapabilityTransport):
    def __init__(self) -> None:
        self.submissions: list[InvocationDelivery] = []

    @property
    def connected(self) -> bool:
        return True

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def discover_node(self, node_id: str) -> NodeAdvertisement:
        raise KeyError(node_id)

    async def submit_invocation(
        self, node_id: str, delivery: InvocationDelivery
    ) -> TransportMessageId:
        del node_id
        self.submissions.append(delivery)
        return invocation_message_id(delivery.invocation.run_id)

    async def flush_outboxes(self, node_id: str) -> int:
        del node_id
        return 0

    async def query_run_status(
        self, node_id: str, run_ref: CapabilityRunRef
    ) -> CapabilityRunStatus | None:
        del node_id, run_ref
        return None

    async def receive(self) -> bytes:
        raise RuntimeError("no messages")

    async def acknowledge(self, acknowledgement: DeliveryAcknowledgement) -> None:
        del acknowledgement

    async def receive_failure(self) -> TransportFailure:
        raise RuntimeError("no failures")


class RecordingSession:
    def __init__(self, workflows: WorkflowService) -> None:
        self.workflows = workflows
        self.receive_calls = 0

    async def receive_pending(self) -> int:
        self.receive_calls += 1
        return 0


class RecordingSessionFactory:
    def __init__(self) -> None:
        self.transport = RecordingTransport()
        self.sessions: list[RecordingSession] = []

    @asynccontextmanager
    async def __call__(
        self,
        database: CoreDatabase,
        configuration: RemoteNodeConfiguration,
    ) -> AsyncIterator[WorkflowCommandSession]:
        del configuration
        registry = CapabilityRegistry(database)
        registry.register_or_refresh_node(_advertisement())
        session = RecordingSession(
            WorkflowService(database, CapabilityRouter(registry, self.transport))
        )
        self.sessions.append(session)
        yield session


class DisconnectedSessionFactory:
    @asynccontextmanager
    async def __call__(
        self,
        database: CoreDatabase,
        configuration: RemoteNodeConfiguration,
    ) -> AsyncIterator[WorkflowCommandSession]:
        del configuration
        raise TransportDisconnected("sensitive transport detail")
        yield RecordingSession(WorkflowService(database))  # pragma: no cover


def _invoke(
    database_path: Path,
    arguments: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
    sessions: WorkflowSessionFactory | None = None,
) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    code = run(
        ["--database", str(database_path), *arguments],
        stdout=stdout,
        stderr=stderr,
        environment={} if environment is None else environment,
        workflow_sessions=RecordingSessionFactory() if sessions is None else sessions,
    )
    return code, stdout.getvalue(), stderr.getvalue()


def _initialize(path: Path) -> None:
    code, _stdout, stderr = _invoke(path, ["core", "init"])
    assert code == 0, stderr


def _definition(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "definition_id": "procedure.test.cli",
                "version": "1",
                "steps": [
                    {
                        "step_id": "execute",
                        "capability_id": "test.cli_capability",
                        "operation": "execute",
                        "inputs": {"message": "from-cli"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _capability_definition() -> CapabilityDefinition:
    return CapabilityDefinition(
        capability_id="test.cli_capability",
        contract_version=CONTRACT_VERSION,
        implementation_version="0.1.0",
        title="CLI test capability",
        description="Exercise WorkflowService through the CLI.",
        operations=(
            OperationDefinition(
                name="execute",
                title="Execute",
                description="Execute the CLI fixture.",
                input_schema=SchemaDeclaration(inline={"type": "object"}),
                result_types=(ResultObjectType.OBSERVATION,),
                retry_semantics=RetrySemantics.SAFE,
            ),
        ),
        execution=ExecutionCharacteristics(
            duration=ExecutionDuration.ONE_SHOT,
            interaction=ExecutionInteraction.STATELESS,
        ),
        interaction_surfaces=InteractionSurfaceDeclaration(
            local_compute=True,
            target_network=False,
            internet_access=False,
            active_session=False,
            managed_resource=False,
        ),
        side_effects=(
            SideEffectDeclaration(
                category=SideEffectCategory.LOCAL_FILESYSTEM,
                level=SideEffectLevel.NONE,
            ),
        ),
        dependencies=(),
    )


def _advertisement() -> NodeAdvertisement:
    definition = _capability_definition()
    return NodeAdvertisement(
        request_message_id=TransportMessageId("transport-handshake:node-cli-test"),
        node_id="node-cli-test",
        timestamp=NOW,
        lifecycle="READY",
        database_ready=True,
        capabilities=(definition,),
        capability_statuses=(
            CapabilityStatusAdvertisement(
                capability_id=definition.capability_id,
                status=AdvertisedCapabilityStatus.AVAILABLE,
            ),
        ),
    )


def test_entry_point_help_and_nonmutating_core_status(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()
    code = run(["--help"], stdout=stdout, stderr=stderr)
    assert code == 0
    assert "Thin operator CLI" in stdout.getvalue()

    database_path = tmp_path / "absent.sqlite3"
    code, output, error = _invoke(database_path, ["--json", "core", "status"])
    assert code == 0 and error == ""
    assert json.loads(output)["exists"] is False
    assert not database_path.exists()


def test_mission_and_asset_create_show_list_json(tmp_path: Path) -> None:
    database_path = tmp_path / "core.sqlite3"
    _initialize(database_path)
    code, output, error = _invoke(
        database_path,
        [
            "--json",
            "mission",
            "create",
            "--mission-ref",
            "mission-cli",
            "--name",
            "CLI lab",
        ],
    )
    assert code == 0 and error == ""
    assert json.loads(output)["mission_ref"] == "mission-cli"

    assert _invoke(database_path, ["mission", "show", "mission-cli"])[0] == 0
    code, output, _error = _invoke(database_path, ["--json", "mission", "list"])
    assert code == 0 and [item["mission_ref"] for item in json.loads(output)] == ["mission-cli"]

    code, output, error = _invoke(
        database_path,
        [
            "--json",
            "asset",
            "add",
            "--asset-ref",
            "asset-cli",
            "--mission",
            "mission-cli",
            "--address",
            "192.0.2.44",
        ],
    )
    assert code == 0 and error == ""
    assert json.loads(output)["asset_ref"] == "asset-cli"
    assert _invoke(database_path, ["asset", "show", "asset-cli"])[0] == 0
    code, output, _error = _invoke(
        database_path, ["--json", "asset", "list", "--mission", "mission-cli"]
    )
    assert code == 0 and json.loads(output)[0]["primary_address"] == "192.0.2.44"


def test_invalid_input_not_found_conflict_and_no_traceback(tmp_path: Path) -> None:
    database_path = tmp_path / "core.sqlite3"
    _initialize(database_path)
    invalid = _invoke(
        database_path,
        ["mission", "create", "--mission-ref", "not valid"],
    )
    assert invalid[0] == 2 and "Traceback" not in invalid[2]
    missing = _invoke(
        database_path,
        [
            "asset",
            "add",
            "--asset-ref",
            "asset-missing",
            "--mission",
            "mission-missing",
            "--address",
            "192.0.2.5",
        ],
    )
    assert missing[0] == 3 and "Traceback" not in missing[2]

    _invoke(database_path, ["mission", "create", "--mission-ref", "mission-duplicate"])
    duplicate = _invoke(database_path, ["mission", "create", "--mission-ref", "mission-duplicate"])
    assert duplicate[0] == 4 and "Traceback" not in duplicate[2]


def test_provider_list_reads_persisted_registry(tmp_path: Path) -> None:
    database_path = tmp_path / "core.sqlite3"
    _initialize(database_path)
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        provider = CapabilityRegistry(database).register_or_refresh_node(_advertisement())[0]
    finally:
        database.dispose()

    code, output, error = _invoke(
        database_path,
        ["--json", "provider", "list", "--capability", "test.cli_capability"],
    )
    assert code == 0 and error == ""
    assert json.loads(output)[0]["provider_id"] == str(provider.provider_id)
    assert _invoke(database_path, ["provider", "show", str(provider.provider_id)])[0] == 0


def test_workflow_start_status_advance_cancel_and_secret_redaction(tmp_path: Path) -> None:
    database_path = tmp_path / "core.sqlite3"
    definition_path = tmp_path / "workflow.json"
    _initialize(database_path)
    _definition(definition_path)
    _invoke(database_path, ["mission", "create", "--mission-ref", "mission-workflow"])
    sessions = RecordingSessionFactory()
    remote = [
        "--node-url",
        "http://localhost:12345/mcp",
        "--node-id",
        "node-cli-test",
        "--json",
    ]
    secret = "never-print-this-bearer"
    code, output, error = _invoke(
        database_path,
        [
            *remote,
            "workflow",
            "start",
            "--mission",
            "mission-workflow",
            "--definition",
            str(definition_path),
            "--workflow-ref",
            "workflow-cli",
        ],
        environment={"BOBERAGENT_MCP_BEARER_TOKEN": secret},
        sessions=sessions,
    )
    assert code == 0 and error == ""
    started = json.loads(output)
    assert started["run"]["workflow_run_ref"] == "workflow-cli"
    assert started["steps"][0]["status"] == "ACTIVE"
    assert len(sessions.transport.submissions) == 1
    assert secret not in output + error

    code, output, _error = _invoke(database_path, ["--json", "workflow", "status", "workflow-cli"])
    assert code == 0 and json.loads(output)["steps"][0]["status"] == "ACTIVE"

    run_ref = CapabilityRunRef(started["steps"][0]["capability_run_ref"])
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        ingestion = ResultIngestionService(database, clock=lambda: NOW)
        ingestion.accept_result(
            CapabilityResult(
                run_ref=run_ref,
                execution_status=CapabilityRunStatus.COMPLETED,
                outcome=CapabilityOutcome(category=CapabilityOutcomeCategory.SUCCESS),
            )
        )
        ingestion.process_ingestion(run_ref)
    finally:
        database.dispose()

    code, output, error = _invoke(
        database_path,
        [*remote, "workflow", "advance", "workflow-cli"],
        environment={"BOBERAGENT_MCP_BEARER_TOKEN": secret},
        sessions=sessions,
    )
    assert code == 0 and error == ""
    assert json.loads(output)["run"]["status"] == "COMPLETED"
    assert sessions.sessions[-1].receive_calls == 1

    cancel_definition = tmp_path / "cancel.json"
    _definition(cancel_definition)
    _invoke(
        database_path,
        [
            *remote,
            "workflow",
            "start",
            "--mission",
            "mission-workflow",
            "--definition",
            str(cancel_definition),
            "--workflow-ref",
            "workflow-cancel",
        ],
        environment={"BOBERAGENT_MCP_BEARER_TOKEN": secret},
        sessions=sessions,
    )
    code, output, _error = _invoke(
        database_path, ["--json", "workflow", "cancel", "workflow-cancel"]
    )
    assert code == 0 and json.loads(output)["run"]["status"] == "CANCELLED"


def test_run_and_world_state_inspection(tmp_path: Path) -> None:
    database_path = tmp_path / "core.sqlite3"
    _initialize(database_path)
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    run_ref = CapabilityRunRef("run-cli-inspection")
    asset_ref = AssetRef("asset-cli-inspection")
    mission_ref = MissionRef("mission-cli-inspection")
    try:
        core = CorePersistence(database)
        core.create_mission(Mission(mission_ref=mission_ref, status="ACTIVE", created_at=NOW))
        core.create_asset(
            Asset(
                asset_ref=asset_ref,
                mission_ref=mission_ref,
                kind="host",
                primary_address="192.0.2.60",
                created_at=NOW,
            )
        )
        core.record_run(
            CapabilityRun(
                run_id=run_ref,
                capability_id="test.cli_capability",
                operation="execute",
                mission_ref=mission_ref,
                status=CapabilityRunStatus.COMPLETED,
                created_at=NOW,
                finished_at=NOW,
            )
        )
        observation = Observation(
            observation_id=ObservationRef("observation-cli-service"),
            type="network.service",
            subject_ref=asset_ref,
            value={
                "transport": "tcp",
                "port": 443,
                "state": "open",
                "service": "https",
            },
            run_ref=run_ref,
            observed_at=NOW,
        )
        core.append_observation(observation)
        core.materialize_observation(observation.observation_id)
    finally:
        database.dispose()

    code, output, error = _invoke(database_path, ["--json", "run", "show", str(run_ref)])
    assert code == 0 and error == ""
    assert json.loads(output)["run"]["run_id"] == str(run_ref)
    code, output, error = _invoke(
        database_path, ["--json", "service", "list", "--asset", str(asset_ref)]
    )
    assert code == 0 and error == ""
    assert json.loads(output)[0]["port"] == 443


def test_malformed_workflow_definition_fails_without_traceback(tmp_path: Path) -> None:
    database_path = tmp_path / "core.sqlite3"
    _initialize(database_path)
    _invoke(database_path, ["mission", "create", "--mission-ref", "mission-malformed"])
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"definition_id":', encoding="utf-8")
    code, output, error = _invoke(
        database_path,
        [
            "--node-url",
            "http://localhost:12345/mcp",
            "--node-id",
            "node-cli-test",
            "workflow",
            "start",
            "--mission",
            "mission-malformed",
            "--definition",
            str(malformed),
        ],
        environment={"BOBERAGENT_MCP_BEARER_TOKEN": "not-disclosed"},
    )
    assert code == 2 and output == ""
    assert "Traceback" not in error and "not-disclosed" not in error


def test_transport_failure_has_stable_exit_without_sensitive_detail(tmp_path: Path) -> None:
    database_path = tmp_path / "core.sqlite3"
    definition_path = tmp_path / "workflow.json"
    _initialize(database_path)
    _definition(definition_path)
    _invoke(database_path, ["mission", "create", "--mission-ref", "mission-transport"])
    code, output, error = _invoke(
        database_path,
        [
            "--node-url",
            "http://localhost:12345/mcp",
            "--node-id",
            "node-unavailable",
            "workflow",
            "start",
            "--mission",
            "mission-transport",
            "--definition",
            str(definition_path),
        ],
        environment={"BOBERAGENT_MCP_BEARER_TOKEN": "never-print-transport-token"},
        sessions=DisconnectedSessionFactory(),
    )
    assert code == 5 and output == ""
    assert "TRANSPORT_DISCONNECTED" in error
    assert "sensitive transport detail" not in error
    assert "never-print-transport-token" not in error
    assert "Traceback" not in error


def test_core_init_reaches_current_revision(tmp_path: Path) -> None:
    database_path = tmp_path / "core.sqlite3"
    _initialize(database_path)
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        assert current_revision(database) is not None
    finally:
        database.dispose()
