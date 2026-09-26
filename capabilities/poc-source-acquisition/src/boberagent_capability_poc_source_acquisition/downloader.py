"""Version-gated curl adapter for one fixed loopback fixture source.

curl >=8.4 enforces --max-filesize while a response with unknown length arrives.
The adapter never enables automatic redirects and never accepts an arbitrary host.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from boberagent_contracts import PoCAcquisitionBounds
from boberagent_sdk import ExecutionContext, ExecutionTimeout

from .errors import AcquisitionRejected


@dataclass(frozen=True, slots=True)
class DownloadedResponse:
    path: Path
    final_uri: str
    request_count: int
    redirect_count: int


class ManagedFixtureDownloader:
    """Use only managed curl and a fixed 127.0.0.1 fixture route."""

    def __init__(
        self,
        ctx: ExecutionContext,
        workspace: Path,
        *,
        port: int,
        bounds: PoCAcquisitionBounds,
    ) -> None:
        self._ctx = ctx
        self._workspace = workspace
        self._port = port
        self._bounds = bounds
        self._request_count = 0
        self._redirect_count = 0
        self._downloaded_bytes = 0
        self._deadline = time.monotonic() + bounds.timeout_seconds

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def redirect_count(self) -> int:
        return self._redirect_count

    @property
    def revision_uri(self) -> str:
        return f"http://127.0.0.1:{self._port}/revision"

    async def fetch(self, route: str) -> DownloadedResponse:
        """Fetch one fixed route, validating every redirect before another request."""

        if route not in {"/revision", "/archive.zip"}:
            raise ValueError("unsupported fixture route")
        current = f"http://127.0.0.1:{self._port}{route}"
        while True:
            self._validate_uri(current)
            if self._request_count >= self._bounds.max_outbound_requests:
                raise AcquisitionRejected("REDIRECT_REJECTED", "outbound request limit exceeded")
            remaining_bytes = self._bounds.max_download_bytes - self._downloaded_bytes
            if route == "/revision":
                remaining_bytes = min(remaining_bytes, 4096)
            if remaining_bytes < 1:
                raise AcquisitionRejected("DOWNLOAD_LIMIT_EXCEEDED", "download budget exhausted")
            remaining_time = self._deadline - time.monotonic()
            if remaining_time <= 0:
                raise ExecutionTimeout("fixture acquisition timed out")
            self._request_count += 1
            output = self._workspace / f"response-{self._request_count}.body"
            args = (
                "-q",  # must be the first curl argument: no ambient .curlrc
                "--silent",
                "--show-error",
                "--globoff",
                "--proto",
                "=http",
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
                str(remaining_bytes),
                "--output",
                str(output),
                "--write-out",
                "%{http_code}\n%{redirect_url}",
                current,
            )
            await self._ctx.cancellation.checkpoint()
            result = await self._ctx.processes.run_tool(
                tool="curl", args=args, timeout=remaining_time
            )
            if result.cancelled:
                raise AcquisitionRejected(
                    "SOURCE_INTEGRITY_INVALID", "managed download was cancelled"
                )
            if result.timed_out or result.exit_code == 28:
                raise ExecutionTimeout("fixture acquisition timed out")
            if result.exit_code == 63:
                output.unlink(missing_ok=True)
                raise AcquisitionRejected(
                    "DOWNLOAD_LIMIT_EXCEEDED", "streaming download limit exceeded"
                )
            if result.exit_code != 0 or result.stdout_artifact_ref is not None:
                output.unlink(missing_ok=True)
                raise AcquisitionRejected("SOURCE_INTEGRITY_INVALID", "managed download failed")
            if not output.is_file():
                raise AcquisitionRejected("SOURCE_INTEGRITY_INVALID", "download produced no file")
            size = output.stat().st_size
            self._downloaded_bytes += size
            if self._downloaded_bytes > self._bounds.max_download_bytes:
                output.unlink(missing_ok=True)
                raise AcquisitionRejected("DOWNLOAD_LIMIT_EXCEEDED", "download budget exceeded")
            if len(result.stdout) > 4096:
                raise AcquisitionRejected(
                    "SOURCE_INTEGRITY_INVALID", "download metadata exceeded bound"
                )
            parts = result.stdout.decode("utf-8", errors="replace").split("\n", 1)
            if len(parts) != 2 or len(parts[0]) != 3 or not parts[0].isdigit():
                raise AcquisitionRejected("SOURCE_INTEGRITY_INVALID", "download status is invalid")
            status = int(parts[0])
            redirect = parts[1].strip()
            if status == 200:
                return DownloadedResponse(
                    path=output,
                    final_uri=current,
                    request_count=self._request_count,
                    redirect_count=self._redirect_count,
                )
            output.unlink(missing_ok=True)
            if status not in {301, 302, 303, 307, 308} or not redirect:
                raise AcquisitionRejected(
                    "REDIRECT_REJECTED", "fixture response is not a valid redirect"
                )
            if self._redirect_count >= self._bounds.max_redirects:
                raise AcquisitionRejected("REDIRECT_REJECTED", "fixture redirect limit exceeded")
            self._validate_uri(redirect)
            self._redirect_count += 1
            current = redirect

    def _validate_uri(self, uri: str) -> None:
        if len(uri) > 2048 or any(ord(char) <= 32 or ord(char) == 127 for char in uri):
            raise AcquisitionRejected("REDIRECT_REJECTED", "fixture destination is malformed")
        parsed = urlsplit(uri)
        try:
            port = parsed.port
        except ValueError as error:
            raise AcquisitionRejected(
                "REDIRECT_REJECTED", "fixture destination has invalid port"
            ) from error
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or port != self._port
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
            or any(part in {".", ".."} for part in parsed.path.split("/"))
        ):
            raise AcquisitionRejected("REDIRECT_REJECTED", "fixture destination is not allowed")
