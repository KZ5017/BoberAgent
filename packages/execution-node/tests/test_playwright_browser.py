"""Optional real Playwright/Chromium smoke test against loopback only."""

from __future__ import annotations

import asyncio
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from boberagent_execution_node.browser import PlaywrightBrowserBackend

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser")


class LocalPageHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"<html><title>real-browser-local</title></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextmanager
def local_page() -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalPageHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.skipif(CHROMIUM is None, reason="explicit local Chromium executable is unavailable")
def test_real_playwright_navigates_controlled_loopback_page() -> None:
    assert CHROMIUM is not None

    async def scenario(server: ThreadingHTTPServer) -> None:
        runtime = await PlaywrightBrowserBackend().launch(
            executable_path=Path(CHROMIUM),
            headless=True,
        )
        session = await runtime.create_session()
        try:
            state = await session.navigate(
                f"http://127.0.0.1:{server.server_port}/",
                allowed_hosts=("127.0.0.1",),
                timeout=15,
            )
            assert state.title == "real-browser-local"
            inspection = await session.inspect(max_html_bytes=100_000)
            assert b"real-browser-local" in inspection.html
        finally:
            await session.close()
            await runtime.close()

    with local_page() as server:
        asyncio.run(scenario(server))
