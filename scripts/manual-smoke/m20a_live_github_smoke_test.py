"""Opt-in M20-A2 live GitHub *metadata-only* research smoke; never acquisition."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from boberagent_cli.operator_env import operator_environment
from boberagent_contracts import AssetRef, MissionRef
from boberagent_core import Asset, CoreDatabase, DatabaseConfig, Mission, upgrade_database
from boberagent_core.research import CoreResearchService, ResearchStatus
from boberagent_core.research.providers import (
    GitHubResearchConfig,
    GitHubResearchProvider,
    github_repository_query,
)
from pydantic import SecretStr

_CVE = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)
_EXPECTED_PROVIDER_DIAGNOSTICS = frozenset(
    {
        "research provider authentication",
        "research provider rate limited",
        "research provider timeout",
        "research provider network",
        "research provider unavailable",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Opt-in, metadata-only GitHub research smoke")
    parser.add_argument("--live-network", action="store_true", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--cve-id", required=True, help="An operator-selected public CVE ID")
    parser.add_argument("--product", help="Optional non-secret product label")
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--result-limit", type=int, default=5)
    return parser


async def _run(args: argparse.Namespace) -> None:
    if not _CVE.fullmatch(args.cve_id):
        raise ValueError("--cve-id must be one explicit CVE identifier")
    if args.database.exists():
        raise ValueError(
            "choose a new database path; the live smoke never overwrites existing state"
        )
    if not args.database.parent.is_dir():
        raise ValueError("database parent directory must already exist")
    if not 0 < args.timeout <= 120 or not 1 <= args.result_limit <= 10:
        raise ValueError("timeout must be 0..120 seconds and result limit 1..10")
    environment = operator_environment(os.environ, project_root=Path(__file__).resolve().parents[2])
    token = environment.get(args.token_env)
    config = GitHubResearchConfig(
        timeout_seconds=min(args.timeout, 10.0),
        token=SecretStr(token) if token else None,
    )
    database = CoreDatabase(DatabaseConfig.sqlite(args.database))
    now = datetime.now(UTC)
    suffix = uuid4().hex
    mission = Mission(
        mission_ref=MissionRef(f"mission-m20a-live-{suffix}"),
        status="ACTIVE",
        created_at=now,
    )
    asset = Asset(
        asset_ref=AssetRef(f"asset-m20a-live-{suffix}"),
        mission_ref=mission.mission_ref,
        kind="host",
        primary_address="192.0.2.60",
        created_at=now,
    )
    try:
        upgrade_database(database)
        with database.unit_of_work() as work:
            work.missions.add(mission)
            work.assets.add(asset)
        research = CoreResearchService(database)
        hypothesis = research.create_hypothesis(
            mission_ref=mission.mission_ref,
            asset_ref=asset.asset_ref,
            claim=f"Public repository research lead for {args.cve_id.upper()}",
            vulnerability_ids=(args.cve_id.upper(),),
            product=args.product,
            provenance="explicit operator live metadata-only smoke",
        )
        async with GitHubResearchProvider(config) as provider:
            attempt = await research.research(
                hypothesis.hypothesis_ref,
                provider,
                result_limit=args.result_limit,
                timeout_seconds=args.timeout,
            )
        hits = research.list_hits(attempt.attempt_ref)
        candidates = research.list_candidates(hypothesis.hypothesis_ref)
        if (
            attempt.status is ResearchStatus.PROVIDER_ERROR
            and attempt.diagnostic not in _EXPECTED_PROVIDER_DIAGNOSTICS
        ):
            raise RuntimeError("unexpected provider or response validation failure")
        print(f"Database: {args.database.resolve()}")
        print(f"Mission: {mission.mission_ref}")
        print(f"Hypothesis: {hypothesis.hypothesis_ref}")
        print(f"Attempt: {attempt.attempt_ref} {attempt.status.value}")
        print(f"Provider/query mapping: {attempt.provider_id}")
        print(f"Outbound metadata query: {github_repository_query(attempt.request)}")
        for hit in hits:
            print(
                f"Hit: {hit.decision.value} {hit.source.source_uri} "
                f"provider_result_id={hit.source.provider_result_id or '-'} "
                f"candidate={hit.candidate_ref or '-'}"
            )
        print(f"Candidates: {', '.join(str(item.candidate_ref) for item in candidates) or '-'}")
    finally:
        database.dispose()

    reopened = CoreDatabase(DatabaseConfig.sqlite(args.database))
    try:
        persisted = CoreResearchService(reopened)
        assert persisted.get_attempt(attempt.attempt_ref) == attempt
        assert persisted.list_hits(attempt.attempt_ref) == hits
        assert persisted.list_candidates(hypothesis.hypothesis_ref) == candidates
        print("Persistence after reopen: verified. No source content downloaded or executed.")
    finally:
        reopened.dispose()


if __name__ == "__main__":
    arguments = _parser().parse_args()
    asyncio.run(_run(arguments))
