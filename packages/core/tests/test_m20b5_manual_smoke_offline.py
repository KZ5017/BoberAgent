"""Offline preflight coverage for the opt-in real-MCP B5 operator script."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from boberagent_core import CoreDatabase, DatabaseConfig, upgrade_database
from boberagent_core.research import (
    DeterministicResearchProvider,
    ResearchResponseStatus,
    ResearchResult,
    SourceClass,
    SourceHit,
)
from test_core_poc_acquisition import _seed


def _smoke() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[3]
        / "scripts/manual-smoke/m20b5_live_github_acquisition_smoke_test.py"
    )
    spec = importlib.util.spec_from_file_location("m20b5_live_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _arguments(
    module: ModuleType, database_path: Path, candidate_ref: str, hit_id: int
) -> list[str]:
    return [
        "--check-config",
        "--database",
        str(database_path),
        "--artifact-root",
        str(database_path.parent / "artifacts"),
        "--candidate-ref",
        candidate_ref,
        "--hit-id",
        str(hit_id),
        "--endpoint",
        "https://kali.example.test:8443/mcp",
        "--node-id",
        "node-offline-check",
    ]


def test_live_flag_is_required_and_help_is_offline(capsys: pytest.CaptureFixture[str]) -> None:
    module = _smoke()
    with pytest.raises(SystemExit) as missing:
        module._parser().parse_args([])
    assert missing.value.code == 2
    with pytest.raises(SystemExit) as help_exit:
        module._parser().parse_args(["--help"])
    assert help_exit.value.code == 0
    assert "--live-network" in capsys.readouterr().out


def test_explicit_historical_selection_and_offline_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _smoke()
    database_path = tmp_path / "core.sqlite3"
    database = CoreDatabase(DatabaseConfig.sqlite(database_path))
    try:
        upgrade_database(database)
        research, candidate_ref, hit_ids, hypothesis = _seed(database)
        provider = DeterministicResearchProvider(
            "github-repository-search-v1",
            (
                ResearchResult(
                    status=ResearchResponseStatus.COMPLETE,
                    hits=(
                        SourceHit(
                            source_class=SourceClass.REPOSITORY,
                            source_uri="https://github.com/example/repo-main",
                            repository_identity="https://github.com/example/repo-main",
                            revision_claim="branch:new",
                            provider_result_id="42",
                            vulnerability_ids=("CVE-2026-1234",),
                            match_excerpt="CVE-2026-1234",
                        ),
                    ),
                ),
            ),
        )
        attempt = asyncio.run(research.research(hypothesis.hypothesis_ref, provider))
        selected_hit_id = research.list_hits(attempt.attempt_ref)[0].hit_id
        args = module._parser().parse_args(
            _arguments(module, database_path, str(candidate_ref), selected_hit_id)
        )
        monkeypatch.setenv("BOBERAGENT_MCP_TOKEN", "test-token-must-not-print")
        configuration = module._configuration(args)
        assert configuration.node_id == "node-offline-check"
        selected = module._selection(database, candidate_ref, selected_hit_id)
        assert selected.hit.hit_id == selected_hit_id
        assert selected.hit.source.revision_claim == "branch:new"
        with pytest.raises(module.SmokeStop, match="historical hit"):
            module._selection(database, candidate_ref, hit_ids[1])
        with pytest.raises(module.SmokeStop, match="historical hit"):
            module._selection(database, candidate_ref, selected_hit_id + 999)
        asyncio.run(module._run(args))
        output = capsys.readouterr().out
        assert f"Historical hit: {selected_hit_id}" in output
        assert "branch:new" in output
        assert "OFFLINE CONFIGURATION VALID" in output
        assert "test-token-must-not-print" not in output
        assert not (tmp_path / "artifacts").exists()
    finally:
        database.dispose()


def test_invalid_configuration_stops_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _smoke()
    monkeypatch.setenv("BOBERAGENT_MCP_TOKEN", "test-token")
    args = module._parser().parse_args(
        _arguments(module, tmp_path / "missing.sqlite3", "poc-candidate-test", 1)
    )
    with pytest.raises(module.SmokeStop, match="existing absolute Core SQLite file"):
        module._configuration(args)
    assert module._bounds().max_outbound_requests >= 6
    assert module._bounds().max_redirects >= 1
    assert module._bounds().max_download_bytes < 64 * 1024 * 1024
