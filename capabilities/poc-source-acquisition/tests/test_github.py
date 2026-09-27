"""Offline GitHub adapter tests: every apparent HTTP response is a process test double."""

from __future__ import annotations

import asyncio
import io
import json
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from boberagent_capability_poc_source_acquisition.capability import PoCSourceAcquisitionCapability
from boberagent_capability_poc_source_acquisition.errors import AcquisitionRejected
from boberagent_capability_poc_source_acquisition.github import (
    GitHubSource,
    ManagedGitHubAcquisition,
)
from boberagent_contracts import (
    CapabilityOutcomeCategory,
    CapabilityRunRef,
    MissionRef,
    PoCSourceAcquisitionInput,
    PoCSourceAcquisitionReceipt,
)
from boberagent_sdk import InvocationContext, ProcessResult
from boberagent_sdk.testing import FakeExecutionContext, FakeProcessService
from test_poc_acquisition_capability import bounds

REPO = "https://github.com/example/repo"
ROOT = "https://api.github.com/repos/example/repo"
SHA = "b" * 40
TREE_SHA = "c" * 40
BRANCH = f"{ROOT}/branches/main"
COMMIT = f"{ROOT}/git/commits/{SHA}"
TREE = f"{ROOT}/git/trees/{TREE_SHA}?recursive=1"
ARCHIVE = f"{ROOT}/zipball/{SHA}"
CODELOAD = f"https://codeload.github.com/example/repo/legacy.zip/{SHA}"


def _archive(entries: list[tuple[str, bytes, int]] | None = None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data, mode in entries or [
            (f"repo-{SHA}/", b"", stat.S_IFDIR | 0o755),
            (f"repo-{SHA}/README.md", b"evidence, never execute\n", stat.S_IFREG | 0o644),
        ]:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return output.getvalue()


def _json(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes = b""
    redirect: str = ""


def _replies(archive: bytes | None = None) -> dict[str, Reply]:
    return {
        ROOT: Reply(
            200,
            _json(
                {
                    "id": 42,
                    "full_name": "example/repo",
                    "html_url": REPO,
                    "private": False,
                    "owner": {"login": "example"},
                }
            ),
        ),
        BRANCH: Reply(200, _json({"name": "main", "commit": {"sha": SHA}})),
        COMMIT: Reply(200, _json({"sha": SHA, "tree": {"sha": TREE_SHA}})),
        TREE: Reply(
            200,
            _json(
                {
                    "sha": TREE_SHA,
                    "truncated": False,
                    "tree": [
                        {"path": "README.md", "mode": "100644", "type": "blob", "sha": "d" * 40}
                    ],
                }
            ),
        ),
        ARCHIVE: Reply(302, redirect=CODELOAD),
        CODELOAD: Reply(200, _archive() if archive is None else archive),
    }


class ScriptedCurl(FakeProcessService):
    def __init__(self, replies: dict[str, Reply]) -> None:
        super().__init__()
        self.replies = replies
        self.uris: list[str] = []
        self.argv: list[tuple[str, ...]] = []

    async def run_tool(
        self, *, tool: str, args: list[str] | tuple[str, ...], timeout: float | None = None
    ) -> ProcessResult:
        argv = tuple(args)
        assert tool == "curl" and timeout is not None and timeout > 0
        assert argv[0] == "-q" and argv[-1].startswith("https://")
        assert "--location" not in argv and "-L" not in argv
        assert argv[argv.index("--proto") + 1] == "=https"
        assert argv[argv.index("--proxy") + 1] == ""
        assert argv[argv.index("--noproxy") + 1] == "*"
        assert "--max-filesize" in argv and "--max-time" in argv
        uri = argv[-1]
        self.uris.append(uri)
        self.argv.append(argv)
        reply = self.replies[uri]
        output = Path(argv[argv.index("--output") + 1])
        ceiling = int(argv[argv.index("--max-filesize") + 1])
        if len(reply.body) > ceiling:
            output.write_bytes(reply.body[:ceiling])
            return ProcessResult(exit_code=63)
        output.write_bytes(reply.body)
        return ProcessResult(exit_code=0, stdout=f"{reply.status}\n{reply.redirect}".encode())


def _input(**updates: object) -> PoCSourceAcquisitionInput:
    data = {
        "acquisition_ref": "poc-acquisition-github-test",
        "source_kind": "github_repository",
        "repository_uri": REPO,
        "provider_repository_id": 42,
        "historical_ref": "branch:main",
        "bounds": bounds(max_outbound_requests=8, max_redirects=2, max_download_bytes=100_000),
    }
    return PoCSourceAcquisitionInput.model_validate({**data, **updates})


async def _acquire(
    replies: dict[str, Reply], *, source: PoCSourceAcquisitionInput | None = None
) -> tuple[GitHubSource, ScriptedCurl]:
    async with FakeExecutionContext() as ctx:
        scripted = ScriptedCurl(replies)
        ctx._processes = scripted
        workspace = await ctx.workspace.create(purpose="github-test")
        result = await ManagedGitHubAcquisition(ctx, workspace.path, source or _input()).acquire()
        assert result.archive.path.read_bytes() == replies[CODELOAD].body
        return result, scripted


def test_valid_historical_branch_resolves_to_full_sha_and_fixed_archive() -> None:
    result, curl = asyncio.run(_acquire(_replies()))
    assert result.resolved_commit_sha == SHA
    assert result.resolved_tree_sha == TREE_SHA
    assert result.historical_ref == "branch:main"
    assert result.validated_repository_uri == REPO
    assert result.validated_provider_repository_id == 42
    assert curl.uris == [ROOT, BRANCH, COMMIT, TREE, ARCHIVE, CODELOAD]
    assert result.archive.final_uri == CODELOAD
    assert result.archive.request_count == 6 and result.archive.redirect_count == 1


@pytest.mark.parametrize(
    ("uri", "reply", "code", "calls"),
    [
        (
            ROOT,
            Reply(
                200,
                _json(
                    {
                        "id": 99,
                        "full_name": "example/repo",
                        "html_url": REPO,
                        "private": False,
                        "owner": {"login": "example"},
                    }
                ),
            ),
            "REPOSITORY_IDENTITY_MISMATCH",
            1,
        ),
        (
            ROOT,
            Reply(
                200,
                _json(
                    {
                        "id": 42,
                        "full_name": "other/repo",
                        "html_url": REPO,
                        "private": False,
                        "owner": {"login": "example"},
                    }
                ),
            ),
            "REPOSITORY_IDENTITY_MISMATCH",
            1,
        ),
        (
            ROOT,
            Reply(
                200,
                _json(
                    {
                        "id": 42,
                        "full_name": "example/repo",
                        "html_url": REPO,
                        "private": True,
                        "owner": {"login": "example"},
                    }
                ),
            ),
            "REPOSITORY_IDENTITY_MISMATCH",
            1,
        ),
        (ROOT, Reply(404), "REPOSITORY_UNAVAILABLE", 1),
        (
            ROOT,
            Reply(301, redirect="https://api.github.com/repos/other/repo"),
            "REPOSITORY_IDENTITY_MISMATCH",
            1,
        ),
        (ROOT, Reply(200, b"{bad"), "GITHUB_RESPONSE_INVALID", 1),
        (ROOT, Reply(429), "GITHUB_RATE_LIMITED", 1),
        (BRANCH, Reply(404), "MUTABLE_REF_UNAVAILABLE", 2),
        (
            BRANCH,
            Reply(200, _json({"name": "main", "commit": {"sha": "a" * 7}})),
            "REVISION_RESOLUTION_FAILED",
            2,
        ),
        (
            BRANCH,
            Reply(200, _json({"name": "main", "commit": {"sha": "z" * 40}})),
            "REVISION_RESOLUTION_FAILED",
            2,
        ),
        (
            BRANCH,
            Reply(200, _json({"name": "other", "commit": {"sha": SHA}})),
            "GITHUB_RESPONSE_INVALID",
            2,
        ),
        (
            TREE,
            Reply(200, _json({"sha": TREE_SHA, "truncated": True, "tree": []})),
            "TREE_TRUNCATED",
            4,
        ),
        (
            TREE,
            Reply(
                200,
                _json(
                    {
                        "sha": TREE_SHA,
                        "truncated": False,
                        "tree": [
                            {"path": "vendor", "mode": "160000", "type": "commit", "sha": "d" * 40}
                        ],
                    }
                ),
            ),
            "SUBMODULE_UNSUPPORTED",
            4,
        ),
        (
            TREE,
            Reply(
                200,
                _json(
                    {
                        "sha": TREE_SHA,
                        "truncated": False,
                        "tree": [
                            {"path": "one", "mode": "160000", "type": "commit", "sha": "d" * 40},
                            {"path": "two", "mode": "160000", "type": "commit", "sha": "e" * 40},
                        ],
                    }
                ),
            ),
            "SUBMODULE_UNSUPPORTED",
            4,
        ),
        (
            TREE,
            Reply(
                200,
                _json(
                    {
                        "sha": TREE_SHA,
                        "truncated": False,
                        "tree": [{"path": "bad", "mode": "100644", "type": "blob", "sha": "short"}],
                    }
                ),
            ),
            "GITHUB_RESPONSE_INVALID",
            4,
        ),
        (ARCHIVE, Reply(302, redirect="https://evil.example/zip"), "ARCHIVE_REDIRECT_REJECTED", 5),
        (ARCHIVE, Reply(302), "ARCHIVE_REDIRECT_REJECTED", 5),
        (
            ARCHIVE,
            Reply(302, redirect=f"http://codeload.github.com/example/repo/zip/{SHA}"),
            "ARCHIVE_REDIRECT_REJECTED",
            5,
        ),
        (CODELOAD, Reply(302, redirect=CODELOAD), "ARCHIVE_REDIRECT_REJECTED", 6),
        (CODELOAD, Reply(429), "GITHUB_RATE_LIMITED", 6),
    ],
)
def test_untrusted_responses_fail_closed(uri: str, reply: Reply, code: str, calls: int) -> None:
    replies = _replies()
    replies[uri] = reply

    async def scenario() -> None:
        async with FakeExecutionContext() as ctx:
            scripted = ScriptedCurl(replies)
            ctx._processes = scripted
            workspace = await ctx.workspace.create(purpose="github-negative")
            with pytest.raises(AcquisitionRejected) as captured:
                await ManagedGitHubAcquisition(ctx, workspace.path, _input()).acquire()
            assert captured.value.code == code
            assert len(scripted.uris) == calls
            assert all(
                host in {"api.github.com", "codeload.github.com"}
                for host in (uri.split("/")[2] for uri in scripted.uris)
            )

    asyncio.run(scenario())


def test_tree_entry_count_and_request_budget_are_bounded() -> None:
    replies = _replies()
    replies[TREE] = Reply(
        200,
        _json(
            {
                "sha": TREE_SHA,
                "truncated": False,
                "tree": [
                    {"path": f"file-{index}", "mode": "100644", "type": "blob", "sha": "d" * 40}
                    for index in range(3)
                ],
            }
        ),
    )

    async def scenario() -> None:
        async with FakeExecutionContext() as ctx:
            scripted = ScriptedCurl(replies)
            ctx._processes = scripted
            workspace = await ctx.workspace.create(purpose="github-bounds")
            with pytest.raises(AcquisitionRejected, match="tree entries exceed bound"):
                await ManagedGitHubAcquisition(
                    ctx,
                    workspace.path,
                    _input(
                        bounds=bounds(
                            max_file_count=2,
                            max_outbound_requests=8,
                            max_redirects=2,
                            max_download_bytes=100_000,
                        )
                    ),
                ).acquire()
            assert len(scripted.uris) == 4
            with pytest.raises(AcquisitionRejected, match="outbound request budget"):
                await ManagedGitHubAcquisition(
                    ctx,
                    workspace.path,
                    _input(
                        bounds=bounds(
                            max_outbound_requests=4,
                            max_redirects=2,
                            max_download_bytes=100_000,
                        )
                    ),
                ).acquire()
            with pytest.raises(AcquisitionRejected, match="redirect budget"):
                await ManagedGitHubAcquisition(
                    ctx,
                    workspace.path,
                    _input(
                        bounds=bounds(
                            max_outbound_requests=8,
                            max_redirects=0,
                            max_download_bytes=100_000,
                        )
                    ),
                ).acquire()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("archive", "code"),
    [
        (
            _archive(
                [
                    (
                        f"repo-{SHA}/pointer",
                        b"version https://git-lfs.github.com/spec/v1\noid sha256:"
                        + b"0" * 64
                        + b"\nsize 1\n",
                        stat.S_IFREG | 0o644,
                    )
                ]
            ),
            "LFS_UNSUPPORTED",
        ),
        (_archive([(f"repo-{SHA}/../escape", b"x", stat.S_IFREG | 0o644)]), "ARCHIVE_PATH_INVALID"),
    ],
)
def test_capability_preserves_raw_evidence_on_unsupported_archive(
    archive: bytes, code: str
) -> None:
    async def scenario() -> None:
        invocation = InvocationContext(
            run_id=CapabilityRunRef("run-github-negative"),
            capability_id="poc.source_acquisition",
            operation="acquire",
            mission_ref=MissionRef("mission-github-test"),
        )
        async with FakeExecutionContext(invocation=invocation) as ctx:
            scripted = ScriptedCurl(_replies(archive))
            ctx._processes = scripted
            result = await PoCSourceAcquisitionCapability().execute("acquire", ctx, _input())
            assert result.outcome.category is CapabilityOutcomeCategory.UNKNOWN
            assert result.outcome.code == code
            assert len(result.artifacts) == 1
            assert await ctx.artifacts.read_bytes(result.artifacts[0].artifact_id) == archive
            assert len(scripted.uris) == 6

    asyncio.run(scenario())


def test_capability_produces_bound_receipt_and_structural_manifest() -> None:
    async def scenario() -> None:
        invocation = InvocationContext(
            run_id=CapabilityRunRef("run-github-success"),
            capability_id="poc.source_acquisition",
            operation="acquire",
            mission_ref=MissionRef("mission-github-test"),
        )
        async with FakeExecutionContext(invocation=invocation) as ctx:
            scripted = ScriptedCurl(_replies())
            ctx._processes = scripted
            result = await PoCSourceAcquisitionCapability().execute("acquire", ctx, _input())
            assert result.outcome.category is CapabilityOutcomeCategory.SUCCESS
            receipt = PoCSourceAcquisitionReceipt.model_validate(
                result.outcome.details["acquisition_receipt"]
            )
            assert receipt.resolved_commit_sha == SHA
            assert receipt.resolved_tree_sha == TREE_SHA
            assert receipt.raw_source.created_by_run == invocation.run_id
            assert receipt.raw_archive_sha256 != SHA
            assert len(result.artifacts) == 2
            assert len(scripted.uris) == 6

    asyncio.run(scenario())


def test_complete_tree_allows_inert_gitmodules_without_gitlinks() -> None:
    archive = _archive(
        [
            (
                f"repo-{SHA}/.gitmodules",
                b'[submodule "old"]\npath=old\nurl=https://invalid\n',
                stat.S_IFREG | 0o644,
            ),
        ]
    )

    async def scenario() -> None:
        invocation = InvocationContext(
            run_id=CapabilityRunRef("run-github-gitmodules"),
            capability_id="poc.source_acquisition",
            operation="acquire",
            mission_ref=MissionRef("mission-github-test"),
        )
        async with FakeExecutionContext(invocation=invocation) as ctx:
            ctx._processes = ScriptedCurl(_replies(archive))
            result = await PoCSourceAcquisitionCapability().execute("acquire", ctx, _input())
            assert result.outcome.category is CapabilityOutcomeCategory.SUCCESS
            assert await ctx.artifacts.read_bytes(result.artifacts[0].artifact_id) == archive

    asyncio.run(scenario())
