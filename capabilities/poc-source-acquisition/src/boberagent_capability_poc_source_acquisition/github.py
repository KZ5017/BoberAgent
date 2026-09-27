"""Fixed-host GitHub identity, revision, tree and SHA-archive acquisition.

GitHub responses are untrusted. Only managed curl touches the network; this adapter
constructs every URL and never runs or extracts repository-controlled content.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from boberagent_contracts import PoCSourceAcquisitionInput
from boberagent_sdk import ExecutionContext, ExecutionTimeout

from .downloader import DownloadedResponse
from .errors import AcquisitionRejected

_SHA = re.compile(r"^[0-9a-f]{40}$")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_API_HEADERS = (
    "Accept: application/vnd.github+json",
    "X-GitHub-Api-Version: 2022-11-28",
    "User-Agent: BoberAgent-PoC-Acquisition/1",
)
_MAX_SMALL_JSON = 64 * 1024
_MAX_TREE_JSON = 8 * 1024 * 1024
_MAX_JSON_DEPTH = 12


@dataclass(frozen=True, slots=True)
class GitHubSource:
    validated_repository_uri: str
    validated_provider_repository_id: int
    repository_validation_uri: str
    historical_ref: str
    resolved_commit_sha: str
    resolved_tree_sha: str
    resolved_at: datetime
    resolution_uri: str
    tree_uri: str
    archive_request_uri: str
    archive: DownloadedResponse


class ManagedGitHubAcquisition:
    """One public GitHub repository, with a shared request/byte/deadline budget."""

    def __init__(
        self, ctx: ExecutionContext, workspace: Path, source: PoCSourceAcquisitionInput
    ) -> None:
        if source.source_kind != "github_repository":
            raise ValueError("GitHub adapter requires github_repository input")
        parsed = urlsplit(source.repository_uri)
        parts = parsed.path[1:].split("/")
        if len(parts) != 2 or any(
            part in {".", ".."} or _NAME.fullmatch(part) is None for part in parts
        ):
            raise AcquisitionRejected(
                "REPOSITORY_IDENTITY_MISMATCH", "repository identity is invalid"
            )
        branch = source.historical_ref.removeprefix("branch:")
        if (
            not source.historical_ref.startswith("branch:")
            or not branch
            or any(not part for part in branch.split("/"))
        ):
            raise AcquisitionRejected("MUTABLE_REF_UNAVAILABLE", "selected branch claim is invalid")
        self._ctx = ctx
        self._workspace = workspace
        self._source = source
        self._owner, self._repo = parts
        self._branch = branch
        self._api_root = f"https://api.github.com/repos/{self._owner}/{self._repo}"
        self._started = time.monotonic()
        self._request_count = 0
        self._redirect_count = 0
        self._downloaded_bytes = 0

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def redirect_count(self) -> int:
        return self._redirect_count

    async def acquire(self) -> GitHubSource:
        repository_uri = self._api_root
        repository = await self._json(repository_uri, _MAX_SMALL_JSON, "REPOSITORY_UNAVAILABLE")
        validated_uri, validated_id = self._validate_repository(repository)
        branch_uri = f"{self._api_root}/branches/{quote(self._branch, safe='')}"
        branch = await self._json(branch_uri, _MAX_SMALL_JSON, "MUTABLE_REF_UNAVAILABLE")
        if not isinstance(branch, dict) or branch.get("name") != self._branch:
            raise AcquisitionRejected("GITHUB_RESPONSE_INVALID", "branch response is invalid")
        commit_summary = branch.get("commit")
        if not isinstance(commit_summary, dict):
            raise AcquisitionRejected("GITHUB_RESPONSE_INVALID", "branch commit is missing")
        commit_sha = _full_sha(commit_summary.get("sha"))
        resolved_at = self._ctx.clock.now()
        commit_uri = f"{self._api_root}/git/commits/{commit_sha}"
        commit = await self._json(commit_uri, _MAX_SMALL_JSON, "REVISION_RESOLUTION_FAILED")
        if not isinstance(commit, dict) or commit.get("sha") != commit_sha:
            raise AcquisitionRejected("GITHUB_RESPONSE_INVALID", "Git commit identity is invalid")
        tree_summary = commit.get("tree")
        if not isinstance(tree_summary, dict):
            raise AcquisitionRejected("GITHUB_RESPONSE_INVALID", "Git commit tree is missing")
        tree_sha = _full_sha(tree_summary.get("sha"))
        tree_uri = f"{self._api_root}/git/trees/{tree_sha}?recursive=1"
        tree = await self._json(tree_uri, _MAX_TREE_JSON, "GITHUB_RESPONSE_INVALID")
        self._validate_tree(tree, tree_sha)
        archive_uri = f"{self._api_root}/zipball/{commit_sha}"
        archive = await self._archive(archive_uri, commit_sha)
        return GitHubSource(
            validated_repository_uri=validated_uri,
            validated_provider_repository_id=validated_id,
            repository_validation_uri=repository_uri,
            historical_ref=self._source.historical_ref,
            resolved_commit_sha=commit_sha,
            resolved_tree_sha=tree_sha,
            resolved_at=resolved_at,
            resolution_uri=branch_uri,
            tree_uri=tree_uri,
            archive_request_uri=archive_uri,
            archive=archive,
        )

    def _validate_repository(self, payload: object) -> tuple[str, int]:
        if not isinstance(payload, dict):
            raise AcquisitionRejected("GITHUB_RESPONSE_INVALID", "repository response is invalid")
        repository_id = payload.get("id")
        if type(repository_id) is not int or repository_id != self._source.provider_repository_id:
            raise AcquisitionRejected(
                "REPOSITORY_IDENTITY_MISMATCH", "repository ID differs from selected hit"
            )
        if (
            payload.get("full_name") != f"{self._owner}/{self._repo}"
            or payload.get("html_url") != self._source.repository_uri
            or payload.get("private") is not False
        ):
            raise AcquisitionRejected(
                "REPOSITORY_IDENTITY_MISMATCH", "repository identity differs from selected hit"
            )
        owner = payload.get("owner")
        if not isinstance(owner, dict) or owner.get("login") != self._owner:
            raise AcquisitionRejected(
                "REPOSITORY_IDENTITY_MISMATCH", "repository owner differs from selected hit"
            )
        assert isinstance(repository_id, int)
        assert isinstance(payload["html_url"], str)
        return payload["html_url"], repository_id

    def _validate_tree(self, payload: object, expected_sha: str) -> None:
        if not isinstance(payload, dict) or payload.get("sha") != expected_sha:
            raise AcquisitionRejected("GITHUB_RESPONSE_INVALID", "Git tree identity is invalid")
        if payload.get("truncated") is True:
            raise AcquisitionRejected("TREE_TRUNCATED", "Git tree response is incomplete")
        if payload.get("truncated") is not False:
            raise AcquisitionRejected("GITHUB_RESPONSE_INVALID", "Git tree completeness is unknown")
        items = payload.get("tree")
        if not isinstance(items, list) or len(items) > self._source.bounds.max_file_count:
            raise AcquisitionRejected("GITHUB_RESPONSE_INVALID", "Git tree entries exceed bound")
        for item in items:
            if not isinstance(item, dict):
                raise AcquisitionRejected("GITHUB_RESPONSE_INVALID", "Git tree item is invalid")
            path = item.get("path")
            mode = item.get("mode")
            kind = item.get("type")
            if (
                not isinstance(path, str)
                or not path
                or len(path.encode("utf-8")) > self._source.bounds.max_path_length
                or _SHA.fullmatch(str(item.get("sha"))) is None
            ):
                raise AcquisitionRejected("GITHUB_RESPONSE_INVALID", "Git tree item is invalid")
            if mode == "160000" and kind == "commit":
                raise AcquisitionRejected("SUBMODULE_UNSUPPORTED", "Gitlink is unsupported")
            if (mode, kind) not in {("040000", "tree"), ("100644", "blob"), ("100755", "blob")}:
                raise AcquisitionRejected("ARCHIVE_UNSUPPORTED", "Git tree object is unsupported")

    async def _archive(self, uri: str, sha: str) -> DownloadedResponse:
        current = uri
        redirected = False
        while True:
            if current != uri:
                self._validate_codeload(current, sha)
            path, status, redirect = await self._request(
                current, self._source.bounds.max_download_bytes
            )
            if status == 200 and redirected:
                return DownloadedResponse(
                    path=path,
                    final_uri=current,
                    request_count=self._request_count,
                    redirect_count=self._redirect_count,
                )
            path.unlink(missing_ok=True)
            if status in {403, 429}:
                raise AcquisitionRejected(
                    "GITHUB_RATE_LIMITED", "GitHub archive request was rate limited or denied"
                )
            if status in {401, 404, 410}:
                raise AcquisitionRejected("REPOSITORY_UNAVAILABLE", "GitHub archive is unavailable")
            if status >= 500:
                raise AcquisitionRejected(
                    "GITHUB_RESPONSE_INVALID", "GitHub archive request failed"
                )
            if status not in {301, 302, 303, 307, 308} or not redirect or redirected:
                raise AcquisitionRejected(
                    "ARCHIVE_REDIRECT_REJECTED", "archive response is invalid"
                )
            if self._redirect_count >= self._source.bounds.max_redirects:
                raise AcquisitionRejected("ARCHIVE_REDIRECT_REJECTED", "redirect budget exceeded")
            self._validate_codeload(redirect, sha)
            self._redirect_count += 1
            current = redirect
            redirected = True

    def _validate_codeload(self, uri: str, sha: str) -> None:
        if len(uri) > 2048 or any(ord(char) <= 32 or ord(char) == 127 for char in uri):
            raise AcquisitionRejected("ARCHIVE_REDIRECT_REJECTED", "archive destination is invalid")
        parsed = urlsplit(uri)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "codeload.github.com"
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            not in {
                f"/{self._owner}/{self._repo}/legacy.zip/{sha}",
                f"/{self._owner}/{self._repo}/zip/{sha}",
            }
        ):
            raise AcquisitionRejected(
                "ARCHIVE_REDIRECT_REJECTED", "archive destination is not allowed"
            )

    async def _json(self, uri: str, cap: int, missing_code: str) -> object:
        path, status, redirect = await self._request(uri, cap)
        if status != 200:
            path.unlink(missing_ok=True)
            if status in {403, 429}:
                raise AcquisitionRejected(
                    "GITHUB_RATE_LIMITED", "GitHub request was rate limited or denied"
                )
            if status in {401, 404, 410}:
                raise AcquisitionRejected(missing_code, "GitHub source endpoint is unavailable")
            if status in {301, 302, 303, 307, 308} or redirect:
                raise AcquisitionRejected(
                    "REPOSITORY_IDENTITY_MISMATCH", "GitHub API redirected unexpectedly"
                )
            raise AcquisitionRejected("GITHUB_RESPONSE_INVALID", "GitHub API request failed")
        try:
            payload = json.loads(path.read_bytes(), object_pairs_hook=_unique_object)
            if _json_depth(payload) > _MAX_JSON_DEPTH:
                raise ValueError("JSON nesting exceeds bound")
            return payload
        except (ValueError, UnicodeDecodeError, RecursionError) as error:
            raise AcquisitionRejected(
                "GITHUB_RESPONSE_INVALID", "GitHub JSON is invalid"
            ) from error
        finally:
            path.unlink(missing_ok=True)

    async def _request(self, uri: str, cap: int) -> tuple[Path, int, str]:
        if self._request_count >= self._source.bounds.max_outbound_requests:
            raise AcquisitionRejected(
                "DOWNLOAD_LIMIT_EXCEEDED", "outbound request budget exhausted"
            )
        if not (
            uri.startswith(self._api_root + "/")
            or uri == self._api_root
            or uri.startswith(f"https://codeload.github.com/{self._owner}/{self._repo}/")
        ):
            raise AcquisitionRejected("ARCHIVE_REDIRECT_REJECTED", "destination is not allowed")
        remaining_bytes = self._source.bounds.max_download_bytes - self._downloaded_bytes
        maximum = min(cap, remaining_bytes)
        if maximum < 1:
            raise AcquisitionRejected("DOWNLOAD_LIMIT_EXCEEDED", "download budget exhausted")
        remaining_time = self._source.bounds.timeout_seconds - (time.monotonic() - self._started)
        if remaining_time <= 0:
            raise ExecutionTimeout("GitHub acquisition timed out")
        self._request_count += 1
        output = self._workspace / f"response-{self._request_count}.body"
        args = (
            "-q",
            "--silent",
            "--show-error",
            "--globoff",
            "--proto",
            "=https",
            "--proxy",
            "",
            "--noproxy",
            "*",
            "--no-location",
            "--max-redirs",
            "0",
            "--max-time",
            f"{remaining_time:.3f}",
            "--max-filesize",
            str(maximum),
            "--output",
            str(output),
            "--write-out",
            "%{http_code}\n%{redirect_url}",
            "--header",
            _API_HEADERS[0],
            "--header",
            _API_HEADERS[1],
            "--header",
            _API_HEADERS[2],
            uri,
        )
        await self._ctx.cancellation.checkpoint()
        result = await self._ctx.processes.run_tool(tool="curl", args=args, timeout=remaining_time)
        if result.timed_out or result.exit_code == 28:
            output.unlink(missing_ok=True)
            raise ExecutionTimeout("GitHub acquisition timed out")
        if result.cancelled:
            output.unlink(missing_ok=True)
            raise AcquisitionRejected("SOURCE_INTEGRITY_INVALID", "managed request was cancelled")
        if result.exit_code == 63:
            output.unlink(missing_ok=True)
            raise AcquisitionRejected(
                "DOWNLOAD_LIMIT_EXCEEDED", "streaming download limit exceeded"
            )
        if result.exit_code != 0 or result.stdout_artifact_ref is not None or not output.is_file():
            output.unlink(missing_ok=True)
            raise AcquisitionRejected("GITHUB_RESPONSE_INVALID", "managed GitHub request failed")
        size = output.stat().st_size
        self._downloaded_bytes += size
        if size > maximum or self._downloaded_bytes > self._source.bounds.max_download_bytes:
            output.unlink(missing_ok=True)
            raise AcquisitionRejected("DOWNLOAD_LIMIT_EXCEEDED", "download budget exceeded")
        if len(result.stdout) > 4096:
            output.unlink(missing_ok=True)
            raise AcquisitionRejected(
                "GITHUB_RESPONSE_INVALID", "GitHub response metadata is invalid"
            )
        pieces = result.stdout.decode("utf-8", errors="replace").split("\n", 1)
        if len(pieces) != 2 or len(pieces[0]) != 3 or not pieces[0].isdigit():
            output.unlink(missing_ok=True)
            raise AcquisitionRejected("GITHUB_RESPONSE_INVALID", "GitHub HTTP status is invalid")
        return output, int(pieces[0]), pieces[1].strip()


def _full_sha(value: object) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise AcquisitionRejected("REVISION_RESOLUTION_FAILED", "Git object SHA is invalid")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate GitHub JSON key")
        result[key] = value
    return result


def _json_depth(value: object) -> int:
    if isinstance(value, dict):
        return 1 + max((_json_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_json_depth(item) for item in value), default=0)
    return 0
