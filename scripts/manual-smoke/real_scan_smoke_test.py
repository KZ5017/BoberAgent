from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from boberagent_contracts import (
    AssetRef,
    CapabilityInvocation,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
)
from boberagent_core import (
    ArtifactStorageConfiguration,
    Asset,
    CapabilityRegistrationClient,
    CapabilityRegistry,
    CapabilityRouter,
    CoreArtifactReceiver,
    CoreArtifactService,
    CoreDatabase,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    FilesystemArtifactStorage,
    Mission,
    ResultIngestionService,
    upgrade_database,
)
from boberagent_transport import (
    AssetProjection,
    InvocationDelivery,
    MissionProjection,
)
from boberagent_transport_mcp import (
    McpClientConfiguration,
    McpTransport,
)
from pydantic import SecretStr

NODE_ID = os.getenv(
    "BOBERAGENT_NODE_ID",
    "node-8724d998-53b2-4fbe-88de-30085a896b46",
)

ENDPOINT = os.getenv(
    "BOBERAGENT_MCP_ENDPOINT",
    "http://192.168.0.11:53177/mcp",
)

TARGET_ADDRESS = os.getenv(
    "BOBERAGENT_SMOKE_TARGET",
    "192.168.0.11",
)

EXPECTED_PORT = int(
    os.getenv(
        "BOBERAGENT_SMOKE_EXPECTED_PORT",
        "80",
    )
)

MISSION_REF = MissionRef("mission-real-kali-smoke")
ASSET_REF = AssetRef("asset-real-kali-smoke")

RUN_REF = CapabilityRunRef(f"run-real-kali-smoke-{uuid.uuid4().hex}")

NOW = datetime.now(UTC)


def build_delivery() -> InvocationDelivery:
    invocation = CapabilityInvocation(
        run_id=RUN_REF,
        capability_id="network.service_discovery",
        operation="discover",
        mission_ref=MISSION_REF,
        inputs={
            "asset_ref": str(ASSET_REF),
            "profile": "quick",
            "timeout_seconds": 120,
        },
    )

    return InvocationDelivery(
        invocation=invocation,
        mission=MissionProjection(
            mission_ref=MISSION_REF,
            name="Real Kali MCP smoke test",
        ),
        allowed_assets=(ASSET_REF,),
        allowed_addresses=(TARGET_ADDRESS,),
        assets=(
            AssetProjection(
                asset_ref=ASSET_REF,
                primary_address=TARGET_ADDRESS,
            ),
        ),
    )


def create_core_state(
    database: CoreDatabase,
    delivery: InvocationDelivery,
) -> None:
    with database.unit_of_work() as work:
        work.missions.add(
            Mission(
                mission_ref=MISSION_REF,
                status="ACTIVE",
                created_at=NOW,
                name="Real Kali MCP smoke test",
            )
        )

        work.assets.add(
            Asset(
                asset_ref=ASSET_REF,
                mission_ref=MISSION_REF,
                kind="host",
                primary_address=TARGET_ADDRESS,
                created_at=NOW,
            )
        )

        work.runs.add(
            CapabilityRun(
                run_id=delivery.invocation.run_id,
                capability_id=delivery.invocation.capability_id,
                operation=delivery.invocation.operation,
                mission_ref=delivery.invocation.mission_ref,
                status=CapabilityRunStatus.CREATED,
                created_at=NOW,
            )
        )


async def main() -> None:
    token = os.environ.get("BOBERAGENT_MCP_TOKEN")

    if not token:
        raise RuntimeError("BOBERAGENT_MCP_TOKEN is not set in this WSL shell.")

    run_directory = Path("/tmp") / f"boberagent-real-scan-{RUN_REF}"
    run_directory.mkdir(parents=True, exist_ok=True)

    database_path = run_directory / "core.sqlite3"
    artifact_root = run_directory / "core-artifacts"

    print("=== BoberAgent real MCP scan ===")
    print(f"Node:       {NODE_ID}")
    print(f"Endpoint:   {ENDPOINT}")
    print(f"Target:     {TARGET_ADDRESS}")
    print(f"Run:        {RUN_REF}")
    print(f"Core data:  {run_directory}")
    print()

    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    upgrade_database(database)

    delivery = build_delivery()
    create_core_state(database, delivery)

    storage = FilesystemArtifactStorage(ArtifactStorageConfiguration(root=artifact_root))

    artifacts = CoreArtifactService(
        database,
        storage,
    )

    artifact_receiver = CoreArtifactReceiver(
        database,
        storage,
    )

    ingestion = ResultIngestionService(database)

    receiver = CoreTransportReceiver(
        database,
        result_ingestion=ingestion,
    )

    registry = CapabilityRegistry(database)

    transport = McpTransport(
        McpClientConfiguration(
            endpoint_url=ENDPOINT,
            node_id=NODE_ID,
            bearer_token=SecretStr(token),
            allow_insecure_remote_transport=True,
        )
    )

    registration = CapabilityRegistrationClient(
        transport,
        registry,
    )

    router = CapabilityRouter(
        registry,
        transport,
    )

    transport_client = CoreTransportClient(
        transport,
        receiver,
    )

    try:
        # -------------------------------------------------
        # 1. REAL MCP CONNECTION + HANDSHAKE
        # -------------------------------------------------

        print("[1] Connecting to Kali Execution Node...")

        await transport.connect()

        advertisement, providers = await registration.refresh_node(NODE_ID)

        print(f"    Connected: {advertisement.node_id} / {advertisement.lifecycle}")

        matching = [
            provider
            for provider in providers
            if provider.capability_id == "network.service_discovery"
        ]

        if not matching:
            raise RuntimeError("network.service_discovery was not advertised.")

        print("    network.service_discovery: AVAILABLE")

        # -------------------------------------------------
        # 2. CORE ROUTING
        # -------------------------------------------------

        print("[2] Selecting capability provider...")

        provider = router.select_provider(
            capability_id=delivery.invocation.capability_id,
            operation=delivery.invocation.operation,
            node_id=NODE_ID,
        )

        print(f"    Provider: {provider.provider_id}")

        # -------------------------------------------------
        # 3. DISPATCH
        # -------------------------------------------------

        print("[3] Dispatching CapabilityInvocation...")

        await router.dispatch(
            invocation=delivery.invocation,
            delivery=delivery,
            provider=provider,
        )

        print("    Invocation accepted.")

        # -------------------------------------------------
        # 4. WAIT FOR REMOTE RUN
        # -------------------------------------------------

        print("[4] Waiting for remote CapabilityRun...")

        final_status = None

        for _ in range(240):
            status = await transport.query_run_status(
                NODE_ID,
                delivery.invocation.run_id,
            )

            if status is not None:
                final_status = status

                if status.is_terminal:
                    break

            await asyncio.sleep(0.5)

        if final_status is None:
            raise RuntimeError("The Node never reported a Run status.")

        if not final_status.is_terminal:
            raise TimeoutError(f"Run did not become terminal: {final_status}")

        print(f"    Remote Run status: {final_status}")

        # -------------------------------------------------
        # 5. ARTIFACT SYNCHRONIZATION
        # -------------------------------------------------

        print("[5] Synchronizing Artifacts...")

        sync_summary = await transport.synchronize_artifacts(
            artifact_receiver,
            chunk_size=64 * 1024,
        )

        print(f"    Synchronized: {sync_summary.synchronized}")

        # -------------------------------------------------
        # 6. EVENT + RESULT DELIVERY
        # -------------------------------------------------

        print("[6] Pulling Event/Result outboxes...")

        count = await transport_client.flush_node(NODE_ID)

        print(f"    Messages available: {count}")

        for _ in range(count):
            await transport_client.receive_one()

        # -------------------------------------------------
        # 7. RESULT INGESTION
        # -------------------------------------------------

        result_envelope = receiver.result_for_run(delivery.invocation.run_id)

        if result_envelope is None:
            raise RuntimeError("No terminal CapabilityResult reached Core.")

        result = result_envelope.result

        print()
        print("=== CapabilityResult ===")
        print(f"Execution:    {result.execution_status}")
        print(f"Outcome:      {result.outcome}")
        print(f"Observations: {len(result.observations)}")
        print(f"Artifacts:    {len(result.artifacts)}")
        print(f"Diagnostics:  {len(result.diagnostics)}")

        # -------------------------------------------------
        # 8. WORLD STATE
        # -------------------------------------------------

        with database.unit_of_work() as work:
            services = tuple(work.services.list_for_asset(ASSET_REF))

        print()
        print("=== Materialized World State ===")

        if not services:
            print("No Services materialized.")
        else:
            for service in sorted(
                services,
                key=lambda item: (
                    item.transport,
                    item.port,
                ),
            ):
                print(
                    f"{service.transport.upper()}"
                    f"/{service.port}"
                    f" state={service.state}"
                    f" service={service.service}"
                    f" product={service.product}"
                    f" version={service.version}"
                )

        # -------------------------------------------------
        # 9. ARTIFACT CHECK
        # -------------------------------------------------

        print()
        print("=== Artifacts ===")

        for descriptor in result.artifacts:
            artifact_ref = descriptor.artifact_id

            available = artifacts.content_available(artifact_ref)

            print(f"{artifact_ref}: content_available={available}")

            if available:
                content = artifacts.read_bytes(artifact_ref)

                print(f"    bytes={len(content)}")

        # -------------------------------------------------
        # 10. EXPECTED REAL SERVICE
        # -------------------------------------------------

        ports = {service.port for service in services}

        print()

        if EXPECTED_PORT not in ports:
            raise RuntimeError(
                f"Expected TCP/{EXPECTED_PORT} "
                f"was not materialized. "
                f"Observed ports: {sorted(ports)}"
            )

        print("SUCCESS: real cross-machine vertical slice completed.")

        print(f"SUCCESS: TCP/{EXPECTED_PORT} was discovered and materialized.")

    finally:
        await transport.disconnect()
        database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
