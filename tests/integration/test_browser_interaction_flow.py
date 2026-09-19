"""Stateful browser capability through neutral transport and the real Node runtime."""

from __future__ import annotations

import asyncio
import http.cookiejar
import re
import sys
import threading
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.client import HTTPMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import IO, cast

from boberagent_contracts import (
    AssetRef,
    CapabilityInvocation,
    CapabilityResult,
    CapabilityRunRef,
    JsonObject,
    MissionRef,
)
from boberagent_core import (
    ArtifactStorageConfiguration,
    CoreArtifactReceiver,
    CoreArtifactService,
    CoreDatabase,
    CoreTransportClient,
    CoreTransportReceiver,
    DatabaseConfig,
    FilesystemArtifactStorage,
)
from boberagent_core.persistence.migrations import upgrade_database
from boberagent_execution_node import (
    ArtifactSyncCoordinator,
    ExecutionNode,
    ExecutionNodeTransportEndpoint,
    NodeConfiguration,
    ToolConfiguration,
)
from boberagent_execution_node.browser import BrowserBackend
from boberagent_sdk import (
    BrowserInspection,
    BrowserPageState,
    ScopeViolation,
    normalize_browser_host,
    parse_browser_url,
)
from boberagent_transport import (
    AssetProjection,
    InMemoryTransport,
    InvocationDelivery,
    MissionProjection,
)

MISSION_REF = MissionRef("mission-browser-integration")
ASSET_REF = AssetRef("asset-browser-integration")
HOST = "127.0.0.1"
TITLE_PATTERN = re.compile(rb"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class BrowserFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/set":
            self.send_response(200)
            self.send_header("Set-Cookie", "browser_state=preserved; Path=/")
            body = b"<html><title>cookie-set</title></html>"
        elif self.path == "/check":
            cookie = self.headers.get("Cookie", "")
            state = b"preserved" if "browser_state=preserved" in cookie else b"missing"
            self.send_response(200)
            body = b"<html><title>cookie-" + state + b"</title></html>"
        elif self.path == "/redirect-outside":
            self.send_response(302)
            port = cast(ThreadingHTTPServer, self.server).server_port
            self.send_header("Location", f"http://localhost:{port}/check")
            body = b""
        else:
            self.send_response(404)
            body = b"<html><title>not-found</title></html>"
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextmanager
def browser_fixture_server() -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer((HOST, 0), BrowserFixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class ScopedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str]) -> None:
        self._allowed_hosts = allowed_hosts

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        if parse_browser_url(newurl).host not in self._allowed_hosts:
            raise ScopeViolation("browser redirect left the authorized host scope")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpFixtureBrowserSession:
    def __init__(self) -> None:
        self._cookies = http.cookiejar.CookieJar()
        self._page = BrowserPageState(final_url="about:blank", title="", status_code=None)
        self._html = b""
        self.closed = False

    @property
    def supported_operations(self) -> tuple[str, ...]:
        return ("navigate", "inspect")

    async def navigate(
        self,
        url: str,
        *,
        allowed_hosts: tuple[str, ...],
        timeout: float | None = None,
    ) -> BrowserPageState:
        if self.closed:
            raise RuntimeError("fixture browser Session is closed")
        normalized = frozenset(normalize_browser_host(host) for host in allowed_hosts)
        if parse_browser_url(url).host not in normalized:
            raise ScopeViolation("browser target host is outside the authorized policy")

        def fetch() -> tuple[str, int, bytes]:
            opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(self._cookies),
                ScopedRedirectHandler(normalized),
            )
            with opener.open(url, timeout=timeout) as response:
                return response.geturl(), response.status, response.read()

        final_url, status, body = await asyncio.to_thread(fetch)
        match = TITLE_PATTERN.search(body)
        title = "" if match is None else match.group(1).decode("utf-8")
        self._html = body
        self._page = BrowserPageState(final_url=final_url, title=title, status_code=status)
        return self._page

    async def inspect(self, *, max_html_bytes: int) -> BrowserInspection:
        if len(self._html) > max_html_bytes:
            raise ValueError("fixture HTML exceeded bound")
        return BrowserInspection(page=self._page, html=self._html)

    async def close(self) -> None:
        self.closed = True


class HttpFixtureBrowserRuntime:
    def __init__(self) -> None:
        self.sessions: list[HttpFixtureBrowserSession] = []
        self.closed = False

    async def create_session(self) -> HttpFixtureBrowserSession:
        session = HttpFixtureBrowserSession()
        self.sessions.append(session)
        return session

    async def close(self) -> None:
        self.closed = True
        for session in self.sessions:
            await session.close()


class HttpFixtureBrowserBackend(BrowserBackend):
    def __init__(self) -> None:
        self.runtimes: list[HttpFixtureBrowserRuntime] = []

    async def launch(self, *, executable_path: Path, headless: bool) -> HttpFixtureBrowserRuntime:
        del executable_path
        assert headless
        runtime = HttpFixtureBrowserRuntime()
        self.runtimes.append(runtime)
        return runtime


def _configuration(tmp_path: Path) -> NodeConfiguration:
    capability_root = Path(__file__).resolve().parents[2] / "capabilities/browser-interaction"
    return NodeConfiguration.for_runtime_directory(
        tmp_path / "node",
        capability_paths=(capability_root,),
        tools={"chromium": ToolConfiguration(executable=sys.executable)},
        configured_node_id="node-browser-integration",
    )


def _delivery(
    run_id: str,
    operation: str,
    inputs: JsonObject,
    *,
    mission_ref: MissionRef = MISSION_REF,
) -> InvocationDelivery:
    return InvocationDelivery(
        invocation=CapabilityInvocation(
            run_id=CapabilityRunRef(run_id),
            capability_id="browser.interaction",
            operation=operation,
            mission_ref=mission_ref,
            inputs=inputs,
        ),
        mission=MissionProjection(mission_ref=mission_ref, name="Browser integration"),
        allowed_assets=(ASSET_REF,),
        allowed_addresses=(HOST,),
        assets=(AssetProjection(asset_ref=ASSET_REF, primary_address=HOST),),
    )


def test_stateful_browser_session_survives_runs_and_closes_through_transport(
    tmp_path: Path,
) -> None:
    with browser_fixture_server() as server:
        database = CoreDatabase(DatabaseConfig.sqlite(tmp_path / "core.sqlite3"))
        upgrade_database(database)
        storage = FilesystemArtifactStorage(
            ArtifactStorageConfiguration(root=tmp_path / "core-artifacts")
        )
        artifact_receiver = CoreArtifactReceiver(database, storage)
        core_artifacts = CoreArtifactService(database, storage)
        backend = HttpFixtureBrowserBackend()

        async def scenario() -> None:
            node = ExecutionNode(_configuration(tmp_path), browser_backend=backend)
            await node.initialize()
            endpoint = ExecutionNodeTransportEndpoint(node)
            transport = InMemoryTransport(queue_capacity=100)
            transport.register_node(endpoint)
            transport.register_artifact_receiver(artifact_receiver)
            receiver = CoreTransportReceiver(database)
            client = CoreTransportClient(transport, receiver)
            await transport.connect()

            async def execute(delivery: InvocationDelivery) -> CapabilityResult:
                await client.submit_invocation(endpoint.node_id, delivery)
                await asyncio.wait_for(transport.wait_for_idle(), timeout=5)
                count = await client.flush_node(endpoint.node_id)
                for _ in range(count):
                    await client.receive_one()
                record = receiver.result_for_run(delivery.invocation.run_id)
                assert record is not None
                return record.result

            try:
                opened = await execute(
                    _delivery("run-browser-open", "open", {"asset_ref": str(ASSET_REF)})
                )
                session_ref = opened.sessions[0].session_id
                assert opened.resources[0].resource_id == opened.sessions[0].resource_refs[0]

                set_result = await execute(
                    _delivery(
                        "run-browser-set-cookie",
                        "navigate",
                        {
                            "asset_ref": str(ASSET_REF),
                            "session_ref": str(session_ref),
                            "url": f"http://{HOST}:{server.server_port}/set",
                        },
                    )
                )
                assert set_result.outcome.code == "BROWSER_NAVIGATED"
                checked = await execute(
                    _delivery(
                        "run-browser-check-cookie",
                        "navigate",
                        {
                            "asset_ref": str(ASSET_REF),
                            "session_ref": str(session_ref),
                            "url": f"http://{HOST}:{server.server_port}/check",
                        },
                    )
                )
                assert checked.outcome.details["title"] == "cookie-preserved"

                cross_mission = await execute(
                    _delivery(
                        "run-browser-wrong-mission",
                        "navigate",
                        {
                            "asset_ref": str(ASSET_REF),
                            "session_ref": str(session_ref),
                            "url": f"http://{HOST}:{server.server_port}/check",
                        },
                        mission_ref=MissionRef("mission-browser-other"),
                    )
                )
                assert cross_mission.outcome.code == "SESSION_UNAVAILABLE"

                inspected = await execute(
                    _delivery(
                        "run-browser-inspect",
                        "inspect",
                        {"asset_ref": str(ASSET_REF), "session_ref": str(session_ref)},
                    )
                )
                artifact_ref = inspected.artifacts[0].artifact_id
                assert node.store is not None
                artifact = node.store.get_artifact(artifact_ref)
                assert artifact is not None
                assert b"cookie-preserved" in Path(artifact.local_path).read_bytes()
                coordinator = ArtifactSyncCoordinator(
                    store=node.store,
                    spool_root=node.configuration.artifact_spool_root,
                    node_id=endpoint.node_id,
                    transport=transport,
                    clock=lambda: datetime.now(UTC),
                    chunk_size=32,
                )
                synchronization = await coordinator.synchronize(artifact_ref)
                assert synchronization.synchronized
                assert b"cookie-preserved" in core_artifacts.read_bytes(artifact_ref)

                rejected = await execute(
                    _delivery(
                        "run-browser-redirect-denied",
                        "navigate",
                        {
                            "asset_ref": str(ASSET_REF),
                            "session_ref": str(session_ref),
                            "url": f"http://{HOST}:{server.server_port}/redirect-outside",
                        },
                    )
                )
                assert rejected.outcome.code == "SCOPE_VIOLATION"

                closed = await execute(
                    _delivery(
                        "run-browser-close",
                        "close",
                        {"asset_ref": str(ASSET_REF), "session_ref": str(session_ref)},
                    )
                )
                assert closed.outcome.code == "BROWSER_SESSION_CLOSED"
                unavailable = await execute(
                    _delivery(
                        "run-browser-after-close",
                        "navigate",
                        {
                            "asset_ref": str(ASSET_REF),
                            "session_ref": str(session_ref),
                            "url": f"http://{HOST}:{server.server_port}/check",
                        },
                    )
                )
                assert unavailable.outcome.code == "SESSION_UNAVAILABLE"
                assert backend.runtimes[0].closed
                assert backend.runtimes[0].sessions[0].closed
            finally:
                await transport.disconnect()
                await node.shutdown()

        try:
            asyncio.run(scenario())
        finally:
            database.dispose()
