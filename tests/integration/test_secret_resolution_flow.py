"""Core-to-Node serialized Secret resolution without a production auth capability."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from boberagent_contracts import (
    CapabilityInvocation,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    SecretRef,
)
from boberagent_core import (
    CoreDatabase,
    CoreSecretService,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    Mission,
    upgrade_database,
)
from boberagent_execution_node import (
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
)
from boberagent_transport import InMemoryTransport, InvocationDelivery, MissionProjection
from transport_test_capability import secret_capability_manifest

NOW = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)


def test_core_grant_resolves_in_capability_across_serialized_transport(
    tmp_path: Path,
) -> None:
    capability_root = tmp_path / "capabilities"
    capability_root.mkdir()
    (capability_root / "capability.json").write_text(
        json.dumps(secret_capability_manifest(), indent=2),
        encoding="utf-8",
    )
    configuration = NodeConfiguration.for_runtime_directory(
        tmp_path / "node-runtime",
        capability_paths=(capability_root,),
        configured_node_id="node-secret-integration",
    )
    database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
    upgrade_database(database)
    mission_ref = MissionRef("mission-secret-integration")
    run_ref = CapabilityRunRef("run-secret-integration")
    plaintext = b"harmless-integrated-secret"
    with database.unit_of_work() as work:
        work.missions.add(Mission(mission_ref=mission_ref, status="ACTIVE", created_at=NOW))
        work.runs.add(
            CapabilityRun(
                run_id=run_ref,
                capability_id="test.secret_consumer",
                operation="verify",
                mission_ref=mission_ref,
                status=CapabilityRunStatus.CREATED,
                created_at=NOW,
            )
        )
    secrets = CoreSecretService(database, clock=lambda: NOW)
    metadata = secrets.store(
        mission_ref=mission_ref,
        value=plaintext,
        secret_type="password",
        secret_ref=SecretRef("secret-integration"),
    )
    invocation = CapabilityInvocation(
        run_id=run_ref,
        capability_id="test.secret_consumer",
        operation="verify",
        mission_ref=mission_ref,
        inputs={
            "secret_ref": str(metadata.secret_ref),
            "expected_sha256": hashlib.sha256(plaintext).hexdigest(),
        },
    )
    delivery = InvocationDelivery(
        invocation=invocation,
        mission=MissionProjection(mission_ref=mission_ref),
        secret_grants=secrets.execution_grants(
            run_ref,
            {metadata.secret_ref: "test.secret_consumer:verify"},
        ),
    )

    async def scenario() -> None:
        node = ExecutionNode(configuration)
        await node.initialize()
        endpoint = ExecutionNodeTransportEndpoint(node)
        transport = InMemoryTransport()
        transport.register_node(endpoint)
        receiver = CoreTransportReceiver(database)
        client = CoreTransportClient(transport, receiver)
        await transport.connect()

        await client.submit_invocation(endpoint.node_id, delivery)
        await asyncio.wait_for(transport.wait_for_idle(), timeout=5)
        count = await client.flush_node(endpoint.node_id)
        for _ in range(count):
            await client.receive_one()

        delivered = receiver.result_for_run(run_ref)
        assert delivered is not None
        assert delivered.result.execution_status is CapabilityRunStatus.COMPLETED
        assert delivered.result.outcome.category.value == "SUCCESS"
        assert plaintext.decode() not in delivered.result.model_dump_json()
        assert node.store is not None
        assert plaintext not in configuration.database_path.read_bytes()
        await transport.disconnect()
        await node.shutdown()

    try:
        asyncio.run(scenario())
        records = secrets.access_records(metadata.secret_ref)
        assert len(records) == 1
        assert records[0].accessor == "CAPABILITY_GRANT"
        assert records[0].run_ref == run_ref
    finally:
        database.dispose()
