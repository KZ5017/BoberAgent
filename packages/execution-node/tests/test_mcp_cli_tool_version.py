"""Operator composition of version-gated managed tools remains explicit."""

from __future__ import annotations

from pathlib import Path

import pytest
from boberagent_execution_node.mcp_cli import _parser, _tools, main


def test_mcp_cli_accepts_an_explicit_curl_version_probe() -> None:
    options = _parser().parse_args(
        [
            "--runtime-directory",
            "/tmp/node-fixture",
            "--tool",
            "curl=/opt/test/curl",
            "--tool-version-arg",
            "curl=--version",
        ]
    )
    tools = _tools(options.tool, options.tool_version_arg)
    assert tools["curl"].executable == "/opt/test/curl"
    assert tools["curl"].version_args == ("--version",)


@pytest.mark.parametrize("value", ["", " ", "\t  "])
def test_mcp_cli_rejects_empty_runtime_before_creating_files(
    value: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["boberagent-node-mcp", "--runtime-directory", value])
    with pytest.raises(SystemExit) as exit_status:
        main()
    assert exit_status.value.code == 2
    assert "--runtime-directory must not be empty" in capsys.readouterr().err
    for name in ("runtime.sqlite3", "node-identity.json", "imported-inputs", "process-output"):
        assert not (tmp_path / name).exists()


def test_mcp_cli_preserves_nonempty_relative_and_absolute_runtime_paths(tmp_path: Path) -> None:
    for value in ("node-runtime", str(tmp_path / "node-runtime")):
        parsed = _parser().parse_args(["--runtime-directory", value])
        assert parsed.runtime_directory == Path(value)


@pytest.mark.parametrize(
    "tools,probes",
    [
        (["curl=/opt/test/curl"], ["unknown=--version"]),
        (["curl=/opt/test/curl"], ["curl="]),
        (["curl=/opt/test/curl"], ["curl=--version", "curl=--help"]),
        (["curl=/opt/test/curl", "curl=/opt/test/other"], []),
    ],
)
def test_mcp_cli_rejects_ambiguous_tool_probe_configuration(
    tools: list[str], probes: list[str]
) -> None:
    with pytest.raises(ValueError):
        _tools(tools, probes)
