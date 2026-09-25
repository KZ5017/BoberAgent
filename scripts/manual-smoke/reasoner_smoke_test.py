"""Manual M19 interpretation/proposal check against an operator-selected chat model.

This deliberately advertises one synthetic provider for validation only. No Node exists and
the proposed action creates no CapabilityRun or transport dispatch.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from boberagent_cli.operator_env import operator_environment
from boberagent_contracts import (
    AssetRef,
    CapabilityDefinition,
    CapabilityRun,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    Observation,
    ObservationRef,
)
from boberagent_core import (
    Asset,
    CapabilityRegistry,
    CoreDatabase,
    CorePersistence,
    DatabaseConfig,
    Goal,
    GoalRef,
    GoalStatus,
    Mission,
    upgrade_database,
)
from boberagent_core.knowledge import KnowledgeId, KnowledgeRouter, ProcedureId
from boberagent_core.reasoning import (
    ContextBuilder,
    OpenAICompatibleReasonerProvider,
    ProposalValidator,
    ReasonerHTTPConfiguration,
    ReasoningSelection,
    ReasoningService,
)
from boberagent_transport import (
    AdvertisedCapabilityStatus,
    CapabilityStatusAdvertisement,
    NodeAdvertisement,
    TransportMessageId,
)
from pydantic import SecretStr


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual, no-execution M19 Reasoner smoke")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="LM_API_TOKEN")
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


async def _run(arguments: argparse.Namespace) -> None:
    root = Path(__file__).resolve().parents[2]
    environment = operator_environment(os.environ, project_root=root)
    token = environment.get(arguments.api_key_env)
    if token is None or not token.strip():
        raise ValueError(f"bearer token environment variable is unset: {arguments.api_key_env}")

    now = datetime.now(UTC)
    mission_ref = MissionRef("mission-manual-reasoner")
    asset_ref = AssetRef("asset-manual-reasoner")
    run_ref = CapabilityRunRef("run-manual-reasoner-evidence")
    observation_ref = ObservationRef("observation-manual-reasoner-http")
    with TemporaryDirectory(prefix="boberagent-m19-") as directory:
        database = CoreDatabase(DatabaseConfig.sqlite(Path(directory) / "core.sqlite3"))
        try:
            upgrade_database(database)
            persistence = CorePersistence(database)
            persistence.create_mission(
                Mission(mission_ref=mission_ref, status="ACTIVE", created_at=now)
            )
            persistence.create_asset(
                Asset(
                    asset_ref=asset_ref,
                    mission_ref=mission_ref,
                    kind="host",
                    primary_address="192.0.2.23",
                    created_at=now,
                )
            )
            goal_ref = GoalRef("goal-manual-reasoner")
            persistence.create_goal(
                Goal(
                    goal_ref=goal_ref,
                    mission_ref=mission_ref,
                    goal_type="service_discovery",
                    status=GoalStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                )
            )
            persistence.record_run(
                CapabilityRun(
                    run_id=run_ref,
                    capability_id="network.service_discovery",
                    operation="discover",
                    mission_ref=mission_ref,
                    status=CapabilityRunStatus.COMPLETED,
                    created_at=now,
                    finished_at=now,
                )
            )
            persistence.append_observation(
                Observation(
                    observation_id=observation_ref,
                    type="network.service",
                    subject_ref=asset_ref,
                    value={
                        "transport": "tcp",
                        "port": 80,
                        "state": "open",
                        "service": "http",
                        "product": None,
                        "version": None,
                    },
                    run_ref=run_ref,
                    observed_at=now,
                )
            )
            persistence.materialize_observation(observation_ref)

            knowledge = KnowledgeRouter.from_directory(root / "knowledge")
            manifest = json.loads(
                (root / "capabilities/network-service-discovery/capability.json").read_text(
                    encoding="utf-8"
                )
            )
            definition = CapabilityDefinition.model_validate(manifest["definition"])
            registry = CapabilityRegistry(database, clock=lambda: now)
            registry.register_or_refresh_node(
                NodeAdvertisement(
                    request_message_id=TransportMessageId("transport-manual-reasoner"),
                    node_id="node-synthetic-reasoner",
                    timestamp=now,
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
            )

            configuration = ReasonerHTTPConfiguration(
                base_url=arguments.base_url,
                model_id=arguments.model,
                api_key=SecretStr(token),
                timeout_seconds=arguments.timeout,
            )
            selection = ReasoningSelection(
                mission_ref=mission_ref,
                goal_ref=goal_ref,
                asset_ref=asset_ref,
                observation_refs=(observation_ref,),
                procedure_id=ProcedureId("procedure.network.service_discovery"),
                canonical_knowledge_ids=(KnowledgeId("knowledge.network.service_evidence"),),
                capability_ids=(definition.capability_id,),
            )
            async with OpenAICompatibleReasonerProvider(configuration) as provider:
                assessment = await ReasoningService(
                    ContextBuilder(database, knowledge, registry),
                    provider,
                    ProposalValidator(database, knowledge, registry),
                ).interpret_and_propose(selection)
            print(assessment.model_dump_json(indent=2))
            print("Advisory only: no Run was created or dispatched for the proposal.")
        finally:
            database.dispose()


def main() -> None:
    parser = _parser()
    try:
        asyncio.run(_run(parser.parse_args()))
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"reasoner smoke failed: {error}\n")


if __name__ == "__main__":
    main()
