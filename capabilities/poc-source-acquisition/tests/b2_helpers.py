"""Local-only fixtures for the bounded acquisition tests."""

from __future__ import annotations

import io
import json
import stat
import time
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

SHA = "a" * 40
REPO = "https://github.com/example/fixture-repo"
REVISION = json.dumps(
    {
        "repository_uri": REPO,
        "provider_repository_id": 42,
        "historical_ref": "branch:main",
        "resolved_commit_sha": SHA,
    },
    sort_keys=True,
).encode()


def zip_bytes(entries: list[tuple[str, bytes, int]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return output.getvalue()


def safe_zip() -> bytes:
    return zip_bytes(
        [
            ("fixture-sha/", b"", stat.S_IFDIR | 0o755),
            ("fixture-sha/README.md", b"harmless evidence\n", stat.S_IFREG | 0o644),
            ("fixture-sha/src/app.py", b"print('never executed')\n", stat.S_IFREG | 0o644),
        ]
    )


class FixtureServer(ThreadingHTTPServer):
    archive: bytes
    revision: bytes
    redirects: dict[str, str | None]
    request_paths: list[str]
    no_length: bool
    delays: dict[str, float]


@contextmanager
def local_server(
    archive: bytes,
    *,
    revision: bytes = REVISION,
    redirects: dict[str, str | None] | None = None,
    no_length: bool = True,
    delays: dict[str, float] | None = None,
) -> Iterator[FixtureServer]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            server.request_paths.append(self.path)
            if self.path in server.delays:
                time.sleep(server.delays[self.path])
            if self.path in server.redirects:
                self.send_response(302)
                location = server.redirects[self.path]
                if location is not None:
                    self.send_header("Location", location)
                self.end_headers()
                return
            if self.path == "/revision":
                body = server.revision
            elif self.path in {"/archive.zip", "/redirected.zip"}:
                body = server.archive
            else:
                self.send_error(404)
                return
            self.send_response(200)
            if not server.no_length:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            with suppress(BrokenPipeError):
                self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            return

    server = FixtureServer(("127.0.0.1", 0), Handler)
    server.archive = archive
    server.revision = revision
    server.redirects = {} if redirects is None else redirects
    server.request_paths = []
    server.no_length = no_length
    server.delays = {} if delays is None else delays
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
