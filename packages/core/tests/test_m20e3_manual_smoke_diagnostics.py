"""Offline checks for the opt-in E3 operator harness's permit clock diagnostics."""

from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path
from types import ModuleType

import pytest
from test_runtime_preparation_e2 import _setup


def _smoke() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[3]
        / "scripts/manual-smoke/m20e3_preparation_import_smoke_test.py"
    )
    spec = importlib.util.spec_from_file_location("m20e3_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_manual_smoke_shows_permit_window_and_short_validity_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database, _plan, _policy, _approvals, _registry, service, request = _setup(tmp_path)
    try:
        admitted = service.admit(request)
        permit = admitted.permit
        assert permit is not None
        smoke = _smoke()
        assert (
            smoke._require_current_permit(admitted, now=permit.not_before + timedelta(minutes=1))
            == permit
        )
        normal = capsys.readouterr().out
        assert permit.not_before.isoformat() in normal
        assert permit.expires_at.isoformat() in normal
        assert "Permit remaining validity: 840s" in normal
        assert "warning" not in normal

        smoke._require_current_permit(admitted, now=permit.expires_at - timedelta(seconds=45))
        short = capsys.readouterr().out
        assert "Permit remaining validity: 45s" in short
        assert "import/replay may not finish in time" in short
    finally:
        database.dispose()


def test_manual_smoke_reports_expired_permit_without_import(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database, _plan, _policy, _approvals, _registry, service, request = _setup(tmp_path)
    try:
        admitted = service.admit(request)
        permit = admitted.permit
        assert permit is not None
        with pytest.raises(ValueError, match="PreparationPermit expired; no Artifact Import"):
            _smoke()._require_current_permit(
                admitted.model_copy(update={"current_applicable": False}),
                now=permit.expires_at + timedelta(seconds=1),
            )
        output = capsys.readouterr().out
        assert permit.expires_at.isoformat() in output
        assert "Permit remaining validity: 0s" in output
    finally:
        database.dispose()
