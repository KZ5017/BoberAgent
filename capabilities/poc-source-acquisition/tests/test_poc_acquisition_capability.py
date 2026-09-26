"""Real Node/managed-curl proof against a loopback-only deterministic fixture."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from b2_helpers import REPO, SHA, local_server, safe_zip, zip_bytes
from boberagent_contracts import (
    CapabilityInvocation,
    CapabilityOutcomeCategory,
    CapabilityRunRef,
    CapabilityRunStatus,
    MissionRef,
    PoCAcquisitionBounds,
    PoCAcquisitionRef,
    PoCSourceAcquisitionInput,
    PoCSourceAcquisitionReceipt,
)
from boberagent_execution_node import (
    ExecutionNode,
    LocalInvocationEnvironment,
    NodeConfiguration,
    ToolConfiguration,
)
from boberagent_execution_node.persistence import WorkspaceState
from boberagent_execution_node.processes.service import ManagedProcessService
from boberagent_sdk import MissionContext, ProcessResult

MISSION = MissionRef("mission-b2-local")
CAPABILITY_ROOT = Path(__file__).resolve().parents[1]


def bounds(**changes: int | float) -> PoCAcquisitionBounds:
    baseline: dict[str, int | float] = {
        "max_download_bytes": 100_000,
        "max_uncompressed_bytes": 20_000,
        "max_single_file_bytes": 10_000,
        "max_file_count": 20,
        "max_directory_depth": 5,
        "max_path_length": 255,
        "max_compression_ratio": 100,
        "max_outbound_requests": 4,
        "max_redirects": 1,
        "timeout_seconds": 10,
    }
    return PoCAcquisitionBounds.model_validate({**baseline, **changes})


def invocation(
    port: int, run: str, *, limits: PoCAcquisitionBounds | None = None
) -> CapabilityInvocation:
    value = PoCSourceAcquisitionInput(
        acquisition_ref=PoCAcquisitionRef("poc-acquisition-b2-fixture"),
        source_kind="loopback_fixture",
        repository_uri=REPO,
        provider_repository_id=42,
        historical_ref="branch:main",
        fixture_port=port,
        bounds=limits or bounds(),
    )
    return CapabilityInvocation(
        run_id=CapabilityRunRef(run),
        capability_id="poc.source_acquisition",
        operation="acquire",
        mission_ref=MISSION,
        inputs=value.model_dump(mode="json"),
    )


def _node(tmp_path: Path) -> ExecutionNode:
    curl = shutil.which("curl")
    if curl is None:
        pytest.skip("managed curl is not installed")
    return ExecutionNode(
        NodeConfiguration.for_runtime_directory(
            tmp_path / "node",
            capability_paths=(CAPABILITY_ROOT,),
            tools={"curl": ToolConfiguration(executable=curl, version_args=("--version",))},
        )
    )


def _environment() -> LocalInvocationEnvironment:
    return LocalInvocationEnvironment(mission=MissionContext(mission_ref=MISSION))


def test_real_node_acquires_exact_raw_bytes_and_deterministic_manifest(tmp_path: Path) -> None:
    archive = safe_zip()
    with local_server(archive) as server:

        async def scenario() -> None:
            node = _node(tmp_path)
            try:
                health = await node.initialize()
                tool = health.tool_summary["curl"]
                assert isinstance(tool, dict) and tool["availability"] == "AVAILABLE"
                assert (
                    node.capabilities.get("poc.source_acquisition").definition.operations[0].name
                    == "acquire"
                )
                call = invocation(server.server_port, "run-b2-success")
                result = await node.execute_local(call, _environment())
                assert result.execution_status is CapabilityRunStatus.COMPLETED
                assert result.outcome.category is CapabilityOutcomeCategory.SUCCESS
                assert result.observations == ()
                assert result.findings == ()
                assert result.effects == ()
                receipt = PoCSourceAcquisitionReceipt.model_validate(
                    result.outcome.details["acquisition_receipt"]
                )
                assert receipt.source_kind == "loopback_fixture"
                assert receipt.resolved_commit_sha == SHA
                assert receipt.raw_archive_sha256 == hashlib.sha256(archive).hexdigest()
                assert receipt.raw_archive_sha256 != receipt.resolved_commit_sha
                assert receipt.request_count == 2 and receipt.redirect_count == 0
                assert len(result.artifacts) == 2
                assert node.store is not None
                raw_record = node.store.get_artifact(receipt.raw_source.artifact_id)
                manifest_record = node.store.get_artifact(receipt.manifest.artifact_id)
                assert raw_record is not None and manifest_record is not None
                assert Path(raw_record.local_path).read_bytes() == archive
                manifest = json.loads(Path(manifest_record.local_path).read_bytes())
                assert manifest["entry_count"] == 2
                assert manifest["archive_root_prefix"] == "fixture-sha/"
                assert all(
                    record.state is WorkspaceState.REMOVED
                    for record in node.store.list_workspaces_for_owner(str(call.run_id))
                )
                assert not any((tmp_path / "node" / "workspaces").iterdir())
            finally:
                await node.shutdown()

        asyncio.run(scenario())
    assert server.request_paths == ["/revision", "/archive.zip"]


@pytest.mark.parametrize(
    "delta,expected",
    [(0, CapabilityOutcomeCategory.SUCCESS), (-1, CapabilityOutcomeCategory.UNKNOWN)],
)
def test_unknown_length_stream_respects_exact_download_budget(
    tmp_path: Path, delta: int, expected: CapabilityOutcomeCategory
) -> None:
    archive = safe_zip()
    from b2_helpers import REVISION

    with local_server(archive, no_length=True) as server:

        async def scenario() -> None:
            node = _node(tmp_path)
            try:
                await node.initialize()
                call = invocation(
                    server.server_port,
                    f"run-b2-bound-{delta}",
                    limits=bounds(max_download_bytes=len(REVISION) + len(archive) + delta),
                )
                result = await node.execute_local(call, _environment())
                assert result.outcome.category is expected
                if delta < 0:
                    assert result.outcome.code == "DOWNLOAD_LIMIT_EXCEEDED"
                    assert result.artifacts == ()
                assert node.store is not None
                assert all(
                    record.state is WorkspaceState.REMOVED
                    for record in node.store.list_workspaces_for_owner(str(call.run_id))
                )
            finally:
                await node.shutdown()

        asyncio.run(scenario())


@pytest.mark.parametrize(
    ("redirect", "expected", "requests"),
    [
        (
            "/redirected.zip",
            CapabilityOutcomeCategory.SUCCESS,
            ["/revision", "/archive.zip", "/redirected.zip"],
        ),
        (
            "http://example.invalid/evil",
            CapabilityOutcomeCategory.UNKNOWN,
            ["/revision", "/archive.zip"],
        ),
        (
            "/archive.zip",
            CapabilityOutcomeCategory.UNKNOWN,
            ["/revision", "/archive.zip", "/archive.zip"],
        ),
        (None, CapabilityOutcomeCategory.UNKNOWN, ["/revision", "/archive.zip"]),
    ],
)
def test_redirects_are_explicit_and_never_contact_disallowed_hosts(
    tmp_path: Path,
    redirect: str | None,
    expected: CapabilityOutcomeCategory,
    requests: list[str],
) -> None:
    with local_server(safe_zip(), redirects={"/archive.zip": redirect}) as server:

        async def scenario() -> None:
            node = _node(tmp_path)
            try:
                await node.initialize()
                result = await node.execute_local(
                    invocation(server.server_port, "run-b2-redirect"), _environment()
                )
                assert result.outcome.category is expected
                if expected is CapabilityOutcomeCategory.UNKNOWN:
                    assert result.outcome.code == "REDIRECT_REJECTED"
            finally:
                await node.shutdown()

        asyncio.run(scenario())
    assert server.request_paths == requests


def test_hostile_archive_retains_only_raw_evidence(tmp_path: Path) -> None:
    import stat

    archive = zip_bytes([("../escape", b"x", stat.S_IFREG | 0o644)])
    with local_server(archive) as server:

        async def scenario() -> None:
            node = _node(tmp_path)
            try:
                await node.initialize()
                result = await node.execute_local(
                    invocation(server.server_port, "run-b2-hostile"), _environment()
                )
                assert result.execution_status is CapabilityRunStatus.COMPLETED
                assert result.outcome.category is CapabilityOutcomeCategory.UNKNOWN
                assert result.outcome.code == "ARCHIVE_PATH_INVALID"
                assert len(result.artifacts) == 1
                assert result.artifacts[0].artifact_type == "poc.source.raw"
                assert "acquisition_receipt" not in result.outcome.details
                assert node.store is not None
                raw = node.store.get_artifact(result.artifacts[0].artifact_id)
                assert raw is not None and Path(raw.local_path).read_bytes() == archive
            finally:
                await node.shutdown()

        asyncio.run(scenario())


def test_managed_curl_argv_blocks_ambient_proxy_and_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    config_home = tmp_path / "untrusted-config"
    config_home.mkdir()
    (config_home / ".curlrc").write_text('proxy = "http://127.0.0.1:1"\n', encoding="utf-8")
    monkeypatch.setenv("CURL_HOME", str(config_home))
    observed: list[tuple[str, tuple[str, ...], float | None]] = []
    original = ManagedProcessService.run_tool

    async def recording(
        self: ManagedProcessService,
        *,
        tool: str,
        args: list[str] | tuple[str, ...],
        timeout: float | None = None,
    ) -> ProcessResult:
        observed.append((tool, tuple(args), timeout))
        return await original(self, tool=tool, args=args, timeout=timeout)

    with (
        local_server(safe_zip()) as server,
        patch.object(ManagedProcessService, "run_tool", recording),
    ):

        async def scenario() -> None:
            node = _node(tmp_path)
            try:
                await node.initialize()
                result = await node.execute_local(
                    invocation(server.server_port, "run-b2-flags"), _environment()
                )
                assert result.outcome.category is CapabilityOutcomeCategory.SUCCESS
            finally:
                await node.shutdown()

        asyncio.run(scenario())
    assert len(observed) == 2
    for tool, args, timeout in observed:
        assert tool == "curl" and timeout is not None and timeout > 0
        assert args[0] == "-q"
        assert "--location" not in args and "-L" not in args
        assert args[args.index("--proxy") + 1] == ""
        assert args[args.index("--noproxy") + 1] == "*"
        assert args[args.index("--proto") + 1] == "=http"
        assert int(args[args.index("--max-filesize") + 1]) > 0
        output = Path(args[args.index("--output") + 1])
        assert output.is_relative_to(tmp_path / "node" / "workspaces")
        assert args[-1].startswith(f"http://127.0.0.1:{server.server_port}/")


def test_request_and_redirect_limits_fail_before_extra_request(tmp_path: Path) -> None:
    with local_server(safe_zip(), redirects={"/archive.zip": "/redirected.zip"}) as server:

        async def scenario() -> None:
            node = _node(tmp_path)
            try:
                await node.initialize()
                one_request = await node.execute_local(
                    invocation(
                        server.server_port,
                        "run-b2-one-request",
                        limits=bounds(max_outbound_requests=1),
                    ),
                    _environment(),
                )
                assert one_request.outcome.code == "REDIRECT_REJECTED"
                no_redirect = await node.execute_local(
                    invocation(
                        server.server_port,
                        "run-b2-no-redirect",
                        limits=bounds(max_redirects=0),
                    ),
                    _environment(),
                )
                assert no_redirect.outcome.code == "REDIRECT_REJECTED"
            finally:
                await node.shutdown()

        asyncio.run(scenario())
    assert server.request_paths == ["/revision", "/revision", "/archive.zip"]


def test_absolute_same_port_redirect_is_allowed(tmp_path: Path) -> None:
    with local_server(safe_zip()) as server:
        server.redirects["/archive.zip"] = f"http://127.0.0.1:{server.server_port}/redirected.zip"

        async def scenario() -> None:
            node = _node(tmp_path)
            try:
                await node.initialize()
                result = await node.execute_local(
                    invocation(server.server_port, "run-b2-absolute-redirect"), _environment()
                )
                assert result.outcome.category is CapabilityOutcomeCategory.SUCCESS
                receipt = PoCSourceAcquisitionReceipt.model_validate(
                    result.outcome.details["acquisition_receipt"]
                )
                assert receipt.redirect_count == 1 and receipt.request_count == 3
                assert receipt.final_archive_uri.endswith("/redirected.zip")
            finally:
                await node.shutdown()

        asyncio.run(scenario())
    assert server.request_paths == ["/revision", "/archive.zip", "/redirected.zip"]


def test_managed_download_timeout_is_terminal_and_workspace_is_clean(tmp_path: Path) -> None:
    with local_server(safe_zip(), delays={"/revision": 0.5}) as server:

        async def scenario() -> None:
            node = _node(tmp_path)
            try:
                await node.initialize()
                call = invocation(
                    server.server_port,
                    "run-b2-timeout",
                    limits=bounds(timeout_seconds=0.05),
                )
                result = await node.execute_local(call, _environment())
                assert result.execution_status is CapabilityRunStatus.TIMED_OUT
                assert result.artifacts == ()
                assert node.store is not None
                assert all(
                    record.state is WorkspaceState.REMOVED
                    for record in node.store.list_workspaces_for_owner(str(call.run_id))
                )
            finally:
                await node.shutdown()

        asyncio.run(scenario())


def test_missing_curl_dependency_prevents_capability_execution(tmp_path: Path) -> None:
    with local_server(safe_zip()) as server:

        async def scenario() -> None:
            node = ExecutionNode(
                NodeConfiguration.for_runtime_directory(
                    tmp_path / "node",
                    capability_paths=(CAPABILITY_ROOT,),
                    tools={"curl": ToolConfiguration(executable=str(tmp_path / "missing-curl"))},
                )
            )
            try:
                await node.initialize()
                result = await node.execute_local(
                    invocation(server.server_port, "run-b2-no-curl"), _environment()
                )
                assert result.execution_status is CapabilityRunStatus.FAILED
                assert result.outcome.code == "DEPENDENCY_UNAVAILABLE"
            finally:
                await node.shutdown()

        asyncio.run(scenario())
    assert server.request_paths == []


@pytest.mark.parametrize(
    ("revision", "code"),
    [
        (b"x" * 5000, "DOWNLOAD_LIMIT_EXCEEDED"),
        (
            b'{"repository_uri":"https://github.com/other/repo","provider_repository_id":42,'
            b'"historical_ref":"branch:main","resolved_commit_sha":"' + SHA.encode() + b'"}',
            "SOURCE_INTEGRITY_INVALID",
        ),
    ],
)
def test_revision_metadata_is_bounded_and_identity_checked(
    tmp_path: Path, revision: bytes, code: str
) -> None:
    with local_server(safe_zip(), revision=revision) as server:

        async def scenario() -> None:
            node = _node(tmp_path)
            try:
                await node.initialize()
                result = await node.execute_local(
                    invocation(server.server_port, "run-b2-revision"), _environment()
                )
                assert result.outcome.category is CapabilityOutcomeCategory.UNKNOWN
                assert result.outcome.code == code
                assert result.artifacts == ()
            finally:
                await node.shutdown()

        asyncio.run(scenario())
    assert server.request_paths == ["/revision"]


def test_corrupt_zip_preserves_raw_bytes_but_never_manifest(tmp_path: Path) -> None:
    archive = safe_zip()[:-12]
    with local_server(archive) as server:

        async def scenario() -> None:
            node = _node(tmp_path)
            try:
                await node.initialize()
                result = await node.execute_local(
                    invocation(server.server_port, "run-b2-truncated"), _environment()
                )
                assert result.outcome.category is CapabilityOutcomeCategory.UNKNOWN
                assert result.outcome.code == "SOURCE_INTEGRITY_INVALID"
                assert len(result.artifacts) == 1
                assert result.artifacts[0].artifact_type == "poc.source.raw"
                assert "acquisition_receipt" not in result.outcome.details
            finally:
                await node.shutdown()

        asyncio.run(scenario())
