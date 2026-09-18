import asyncio
import os
from pathlib import Path

from pydantic import SecretStr

from boberagent_core import (
    CapabilityRegistry,
    CoreDatabase,
    DatabaseConfig,
    upgrade_database,
)
from boberagent_core.capabilities.mcp import CoreMcpNodeConnection
from boberagent_transport_mcp import McpClientConfiguration


NODE_ID = "node-8724d998-53b2-4fbe-88de-30085a896b46"
ENDPOINT = "http://192.168.0.11:53177/mcp"

token = os.environ["BOBERAGENT_MCP_TOKEN"]

runtime = Path("/tmp/boberagent-real-mcp-smoke")
runtime.mkdir(parents=True, exist_ok=True)

database = CoreDatabase(
    DatabaseConfig.sqlite(runtime / "core.sqlite3")
)
upgrade_database(database)

registry = CapabilityRegistry(database)

configuration = McpClientConfiguration(
    endpoint_url=ENDPOINT,
    node_id=NODE_ID,
    bearer_token=SecretStr(token),
    allow_insecure_remote_transport=True,
)

connection = CoreMcpNodeConnection(
    configuration=configuration,
    registry=registry,
)


async def main():
    try:
        advertisement, providers = await connection.connect_and_refresh()

        print()
        print("=== MCP HANDSHAKE OK ===")
        print(f"Node ID:     {advertisement.node_id}")
        print(f"Lifecycle:   {advertisement.lifecycle}")
        print()
        print("Providers:")

        for provider in providers:
            print(provider.model_dump_json(indent=2))

        matching = [
            provider
            for provider in providers
            if provider.capability_id == "network.service_discovery"
        ]

        print()
        if matching:
            print("SUCCESS: network.service_discovery provider is registered.")
        else:
            raise RuntimeError(
                "Handshake succeeded, but network.service_discovery "
                "was not advertised by the Kali Node."
            )

    finally:
        await connection.disconnect()
        database.dispose()


asyncio.run(main())
