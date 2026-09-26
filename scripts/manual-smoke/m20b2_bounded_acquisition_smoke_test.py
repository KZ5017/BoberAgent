"""Offline M20-B2 Node/curl/ZIP smoke; contacts 127.0.0.1 only."""

from __future__ import annotations

import asyncio
import io
import json
import shutil
import stat
import tempfile
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from boberagent_contracts import (
    CapabilityInvocation,
    CapabilityOutcomeCategory,
    CapabilityRunRef,
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
from boberagent_sdk import MissionContext

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
REPO = "https://github.com/example/offline-fixture"
MISSION = MissionRef("mission-offline-b2")


def _zip(name: str, content: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        root = zipfile.ZipInfo("fixture-sha/")
        root.create_system = 3
        root.external_attr = (stat.S_IFDIR | 0o755) << 16
        archive.writestr(root, b"")
        entry = zipfile.ZipInfo(name)
        entry.create_system = 3
        entry.external_attr = (stat.S_IFREG | 0o644) << 16
        entry.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(entry, content)
    return output.getvalue()


def _bounds() -> PoCAcquisitionBounds:
    return PoCAcquisitionBounds(
        max_download_bytes=100_000,
        max_uncompressed_bytes=10_000,
        max_single_file_bytes=10_000,
        max_file_count=10,
        max_directory_depth=5,
        max_path_length=255,
        max_compression_ratio=100,
        max_outbound_requests=3,
        max_redirects=0,
        timeout_seconds=10,
    )


def _invocation(port: int, run: str) -> CapabilityInvocation:
    value = PoCSourceAcquisitionInput(
        acquisition_ref=PoCAcquisitionRef(f"poc-acquisition-{run}"),
        source_kind="loopback_fixture",
        repository_uri=REPO,
        provider_repository_id=42,
        historical_ref="branch:main",
        fixture_port=port,
        bounds=_bounds(),
    )
    return CapabilityInvocation(
        run_id=CapabilityRunRef(run),
        capability_id="poc.source_acquisition",
        operation="acquire",
        mission_ref=MISSION,
        inputs=value.model_dump(mode="json"),
    )


class FixtureServer(ThreadingHTTPServer):
    archive: bytes


async def _run(server: FixtureServer, runtime: Path, curl: str) -> None:
    node = ExecutionNode(
        NodeConfiguration.for_runtime_directory(
            runtime,
            capability_paths=(ROOT / "capabilities/poc-source-acquisition",),
            tools={"curl": ToolConfiguration(executable=curl, version_args=("--version",))},
        )
    )
    await node.initialize()
    try:
        environment = LocalInvocationEnvironment(mission=MissionContext(mission_ref=MISSION))
        good = await node.execute_local(_invocation(server.server_port, "run-b2-good"), environment)
        assert good.outcome.category is CapabilityOutcomeCategory.SUCCESS
        receipt = PoCSourceAcquisitionReceipt.model_validate(
            good.outcome.details["acquisition_receipt"]
        )
        assert node.store is not None
        raw = node.store.get_artifact(receipt.raw_source.artifact_id)
        manifest = node.store.get_artifact(receipt.manifest.artifact_id)
        assert raw is not None and manifest is not None
        assert Path(raw.local_path).read_bytes() == server.archive
        structured = json.loads(Path(manifest.local_path).read_bytes())
        assert structured["entry_count"] == 1
        print(
            json.dumps(
                {
                    "resolved_fixture_revision": receipt.resolved_commit_sha,
                    "raw_artifact_ref": str(receipt.raw_source.artifact_id),
                    "raw_sha256": receipt.raw_archive_sha256,
                    "raw_size": receipt.raw_archive_size_bytes,
                    "manifest_artifact_ref": str(receipt.manifest.artifact_id),
                    "manifest_sha256": receipt.manifest_sha256,
                    "entry_count": structured["entry_count"],
                    "total_uncompressed_bytes": structured["total_uncompressed_bytes"],
                },
                sort_keys=True,
            )
        )
        server.archive = _zip("fixture-sha/../escape", b"unsafe")
        bad = await node.execute_local(
            _invocation(server.server_port, "run-b2-hostile"), environment
        )
        assert bad.outcome.category is CapabilityOutcomeCategory.UNKNOWN
        assert bad.outcome.code == "ARCHIVE_PATH_INVALID"
        assert len(bad.artifacts) == 1 and "acquisition_receipt" not in bad.outcome.details
        assert not any((runtime / "workspaces").iterdir())
        print("offline M20-B2 PASS: valid fixture retained; traversal ZIP rejected; no extraction")
    finally:
        await node.shutdown()


def main() -> None:
    curl = shutil.which("curl")
    if curl is None:
        raise SystemExit("managed curl >=8.4 is required for this offline smoke")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/revision":
                body = json.dumps(
                    {
                        "repository_uri": REPO,
                        "provider_repository_id": 42,
                        "historical_ref": "branch:main",
                        "resolved_commit_sha": SHA,
                    },
                    sort_keys=True,
                ).encode()
            elif self.path == "/archive.zip":
                body = server.archive
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            return

    server = FixtureServer(("127.0.0.1", 0), Handler)
    server.archive = _zip("fixture-sha/README.md", b"evidence only; never executed\n")
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="boberagent-m20b2-") as temporary:
            asyncio.run(_run(server, Path(temporary) / "node", curl))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
