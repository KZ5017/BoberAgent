"""Manual WSL Core to Kali Node Secret resolution proof over real MCP."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from boberagent_contracts import (
    CapabilityInvocation,
    CapabilityOutcomeCategory,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
)
from boberagent_core import (
    CoreDatabase,
    CoreSecretService,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    Mission,
    ResultIngestionService,
    ResultIngestionStatus,
    upgrade_database,
)
from boberagent_transport import InvocationDelivery, MissionProjection
from boberagent_transport_mcp import McpClientConfiguration, McpTransport
from pydantic import SecretStr

_CAPABILITY_ID = "test.secret_consumer"
_OPERATION = "verify"
_SYNTHETIC_VALUE = b"harmless-m16-cross-machine-smoke-value"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prove an authorized Core Secret grant across real MCP"
    )
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--core-runtime-directory", type=Path, required=True)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--allow-insecure-remote-transport", action="store_true")
    parser.add_argument("--token-environment-variable", default="BOBERAGENT_MCP_TOKEN")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    return parser


async def _run(arguments: argparse.Namespace) -> None:
    token = os.environ.get(arguments.token_environment_variable)
    if not token:
        raise RuntimeError(
            f"bearer token environment variable is unset: {arguments.token_environment_variable}"
        )
    if arguments.timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    if not arguments.core_runtime_directory.is_absolute():
        raise ValueError("--core-runtime-directory must be an absolute path")

    runtime_directory: Path = arguments.core_runtime_directory
    runtime_directory.mkdir(parents=True, exist_ok=True)
    database_path = runtime_directory / "core.sqlite3"
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database)
        suffix = uuid.uuid4().hex
        mission_ref = MissionRef(f"mission-manual-secret-smoke-{suffix}")
        run_ref = CapabilityRunRef(f"run-manual-secret-smoke-{suffix}")
        now = datetime.now(UTC)
        with database.unit_of_work() as work:
            work.missions.add(
                Mission(
                    mission_ref=mission_ref,
                    status="ACTIVE",
                    created_at=now,
                    name="Manual cross-machine Secret resolution smoke",
                )
            )
            work.runs.add(
                CapabilityRun(
                    run_id=run_ref,
                    capability_id=_CAPABILITY_ID,
                    operation=_OPERATION,
                    mission_ref=mission_ref,
                    status=CapabilityRunStatus.CREATED,
                    created_at=now,
                )
            )

        secrets = CoreSecretService(database)
        secret = secrets.store(
            mission_ref=mission_ref,
            value=_SYNTHETIC_VALUE,
            secret_type="password",
            metadata={"fixture": "manual-secret-resolution-smoke"},
        )
        invocation = CapabilityInvocation(
            run_id=run_ref,
            capability_id=_CAPABILITY_ID,
            operation=_OPERATION,
            mission_ref=mission_ref,
            inputs={
                "secret_ref": str(secret.secret_ref),
                "expected_sha256": hashlib.sha256(_SYNTHETIC_VALUE).hexdigest(),
            },
        )
        delivery = InvocationDelivery(
            invocation=invocation,
            mission=MissionProjection(
                mission_ref=mission_ref,
                name="Manual cross-machine Secret resolution smoke",
            ),
            secret_grants=secrets.execution_grants(
                run_ref,
                {secret.secret_ref: f"{_CAPABILITY_ID}:{_OPERATION}"},
            ),
        )

        print(f"Core database: {database_path}")
        print(f"MissionRef:    {mission_ref}")
        print(f"SecretRef:     {secret.secret_ref}")
        print(f"RunRef:        {run_ref}")

        verify_tls: bool | Path = arguments.ca_file if arguments.ca_file is not None else True
        transport = McpTransport(
            McpClientConfiguration(
                endpoint_url=arguments.endpoint,
                node_id=arguments.node_id,
                bearer_token=SecretStr(token),
                verify_tls=verify_tls,
                allow_insecure_remote_transport=arguments.allow_insecure_remote_transport,
            )
        )
        ingestion = ResultIngestionService(database)
        receiver = CoreTransportReceiver(database, result_ingestion=ingestion)
        client = CoreTransportClient(transport, receiver)
        try:
            await transport.connect()
            advertisement = await client.discover_node(arguments.node_id)
            if not any(
                str(definition.capability_id) == _CAPABILITY_ID
                and any(operation.name == _OPERATION for operation in definition.operations)
                for definition in advertisement.capabilities
            ):
                raise RuntimeError("Node did not advertise test.secret_consumer/verify")

            await client.submit_invocation(arguments.node_id, delivery)
            deadline = asyncio.get_running_loop().time() + arguments.timeout_seconds
            while asyncio.get_running_loop().time() < deadline:
                status = await transport.query_run_status(arguments.node_id, run_ref)
                if status is not None and status.is_terminal:
                    break
                await asyncio.sleep(0.25)
            else:
                raise TimeoutError(f"Secret consumer Run did not become terminal: {run_ref}")

            count = await client.flush_node(arguments.node_id)
            for _ in range(count):
                await client.receive_one()
            envelope = receiver.result_for_run(run_ref)
            if envelope is None:
                raise RuntimeError(f"no CapabilityResult reached Core for {run_ref}")
            result = envelope.result
            if result.execution_status is not CapabilityRunStatus.COMPLETED:
                raise RuntimeError(f"Secret consumer execution ended as {result.execution_status}")
            if result.outcome.category is not CapabilityOutcomeCategory.SUCCESS:
                raise RuntimeError(f"Secret consumer outcome was {result.outcome.category}")
            if _SYNTHETIC_VALUE.decode("ascii") in result.model_dump_json():
                raise RuntimeError("CapabilityResult unexpectedly contains the synthetic Secret")

            record = ingestion.get_ingestion(run_ref)
            if record is None or record.status is not ResultIngestionStatus.PROCESSED:
                raise RuntimeError(f"Core Result ingestion did not complete for {run_ref}")
            with database.unit_of_work() as work:
                core_run = work.runs.get(run_ref)
            if core_run is None or core_run.status is not CapabilityRunStatus.COMPLETED:
                raise RuntimeError(f"Core CapabilityRun did not become COMPLETED: {run_ref}")
            accesses = secrets.access_records(secret.secret_ref)
            if len(accesses) != 1 or (
                accesses[0].accessor != "CAPABILITY_GRANT" or accesses[0].run_ref != run_ref
            ):
                raise RuntimeError("Core Secret grant audit does not match the Run")
            print("SUCCESS: Core Secret resolved by the Kali fixture; Result ingested.")
        finally:
            await transport.disconnect()
    finally:
        database.dispose()


def main() -> None:
    asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    main()
