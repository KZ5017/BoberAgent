"""Operator composition of version-gated managed tools remains explicit."""

from __future__ import annotations

import pytest
from boberagent_execution_node.mcp_cli import _parser, _tools


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
