"""Operator-local configuration is opt-in at entrypoints and never leaks into globals."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from importlib import import_module
from pathlib import Path
from typing import TextIO

import pytest
from boberagent_cli.main import main
from boberagent_cli.operator_env import operator_environment


def test_missing_default_file_is_harmless(tmp_path: Path) -> None:
    source = {"EXISTING": "process-value"}

    assert operator_environment(source, project_root=tmp_path) == source
    assert source == {"EXISTING": "process-value"}


def test_local_file_parsing_and_process_precedence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".env.local").write_text(
        "# operator comment\n\nLM_API_TOKEN=local-test-value\nOTHER_KEY='quoted value'\n",
        encoding="utf-8",
    )
    source = {"LM_API_TOKEN": "process-test-value"}

    merged = operator_environment(source, project_root=tmp_path)

    assert merged["LM_API_TOKEN"] == "process-test-value"
    assert merged["OTHER_KEY"] == "quoted value"
    assert source == {"LM_API_TOKEN": "process-test-value"}
    assert "OTHER_KEY" not in os.environ
    captured = capsys.readouterr()
    assert "local-test-value" not in captured.out + captured.err


def test_semantic_smoke_token_can_come_from_local_file(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text("LM_API_TOKEN=synthetic-token\n", encoding="utf-8")

    environment = operator_environment({}, project_root=tmp_path)

    assert environment.get("LM_API_TOKEN") == "synthetic-token"


def test_explicit_file_override_and_missing_override(tmp_path: Path) -> None:
    import pytest

    selected = tmp_path / "private.env"
    selected.write_text("LM_API_TOKEN=override-value\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("LM_API_TOKEN=default-value\n", encoding="utf-8")

    assert (
        operator_environment({"BOBERAGENT_ENV_FILE": "private.env"}, project_root=tmp_path)[
            "LM_API_TOKEN"
        ]
        == "override-value"
    )
    with pytest.raises(ValueError, match="explicit local environment file does not exist"):
        operator_environment({"BOBERAGENT_ENV_FILE": "missing.env"}, project_root=tmp_path)


def test_cli_main_loads_local_file_without_printing_value(
    tmp_path: Path, monkeypatch: object, capsys: object
) -> None:
    import pytest

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    assert isinstance(capsys, pytest.CaptureFixture)
    (tmp_path / ".env.local").write_text("LM_API_TOKEN=synthetic-cli-token\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOBERAGENT_ENV_FILE", raising=False)
    monkeypatch.delenv("LM_API_TOKEN", raising=False)
    received: dict[str, str] = {}

    def fake_run(
        argv: Sequence[str] | None,
        *,
        stdout: TextIO,
        stderr: TextIO,
        environment: Mapping[str, str] | None = None,
    ) -> int:
        del argv, stdout, stderr
        assert environment is not None
        received.update(environment)
        return 0

    monkeypatch.setattr(import_module("boberagent_cli.main"), "run", fake_run)

    assert main(["--help"]) == 0
    assert received["LM_API_TOKEN"] == "synthetic-cli-token"
    assert "LM_API_TOKEN" not in os.environ
    captured = capsys.readouterr()
    assert "synthetic-cli-token" not in captured.out + captured.err
