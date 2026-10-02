"""E4 exact-source unit tests use inert bytes, never import/execute archive members."""

import hashlib
import json
import stat
import warnings
import zipfile
from pathlib import Path

import pytest
from boberagent_contracts.runtime_preparation import PreparationBudgets
from boberagent_execution_node.preparation.materializer import (
    MaterializationError,
    materialize_zip,
    parse_manifest,
    verify_published,
)


def _budgets(**changes: int) -> PreparationBudgets:
    values = {
        "max_imported_artifact_bytes": 1_000_000,
        "max_materialized_bytes": 1_000_000,
        "max_file_count": 20,
        "max_path_depth": 10,
        "max_temporary_bytes": 1_000_000,
        "max_preparation_write_bytes": 1_000_000,
        "max_processes": 2,
        "max_process_runtime_seconds": 5,
        "max_total_runtime_seconds": 10,
        "max_captured_output_bytes": 1000,
        "max_memory_bytes": 1_000_000,
    }
    values.update(changes)
    return PreparationBudgets.model_validate(values)


def _fixture(
    tmp_path: Path,
    members: list[tuple[str, bytes, int]],
    *,
    entries: list[dict[str, object]] | None = None,
    root: str | None = "source/",
) -> tuple[Path, bytes]:
    archive_path = tmp_path / "source.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(archive_path, "w") as archive:
            for name, content, mode in members:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = mode << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content)
    if entries is None:
        entries = [
            {
                "path": name.removeprefix(root or "").rstrip("/"),
                "type": "directory" if name.endswith("/") else "file",
                "mode": mode & 0o777,
                "executable": None if name.endswith("/") else bool(mode & 0o111),
                "size_bytes": None if name.endswith("/") else len(content),
                "sha256": None if name.endswith("/") else hashlib.sha256(content).hexdigest(),
            }
            for name, content, mode in members
        ]
    entries.sort(key=lambda item: str(item["path"]))
    manifest = {
        "format_version": "poc-source-manifest-v1",
        "archive_representation": "github_zip",
        "resolved_commit_sha": "a" * 40,
        "raw_archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "raw_archive_size_bytes": archive_path.stat().st_size,
        "archive_root_prefix": root,
        "entry_count": len(entries),
        "total_uncompressed_bytes": sum(
            item["size_bytes"] if isinstance(item["size_bytes"], int) else 0
            for item in entries
            if item["type"] == "file"
        ),
        "entries": entries,
    }
    return archive_path, json.dumps(manifest).encode()


def _parse(archive: Path, data: bytes, budgets: PreparationBudgets):  # type: ignore[no-untyped-def]
    return parse_manifest(
        data,
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        archive.stat().st_size,
        "a" * 40,
        budgets,
    )


def test_exact_zip_is_published_read_only_and_reverified(tmp_path: Path) -> None:
    members = [
        ("source/src/", b"", stat.S_IFDIR | 0o755),
        ("source/src/checker.py", b"print('inert')\n", stat.S_IFREG | 0o644),
    ]
    archive, data = _fixture(tmp_path, members)
    budgets = _budgets()
    manifest = _parse(archive, data, budgets)
    destination = tmp_path / "stage"
    destination.mkdir()
    result = materialize_zip(
        archive, manifest, destination, budgets, started=__import__("time").monotonic()
    )
    assert result.file_count == 1
    assert result.byte_count == len(members[1][1])
    assert (destination / "src/checker.py").read_bytes() == members[1][1]
    assert not (destination / "src/checker.py").stat().st_mode & 0o222
    destination.chmod(0o555)  # Owner service's atomic publication boundary.
    verify_published(destination, manifest, result)
    (destination / "src/checker.py").chmod(0o644)
    with pytest.raises(MaterializationError, match="PREPARED_CONTENT_MISMATCH"):
        verify_published(destination, manifest, result)


@pytest.mark.parametrize(
    "name,mode",
    [
        ("source/../escape", stat.S_IFREG | 0o644),
        ("/absolute", stat.S_IFREG | 0o644),
        ("source/link", stat.S_IFLNK | 0o777),
        ("source/device", stat.S_IFCHR | 0o644),
        ("source/a/b/c/d/e/f", stat.S_IFREG | 0o644),
    ],
)
def test_hostile_members_never_escape(tmp_path: Path, name: str, mode: int) -> None:
    archive, data = _fixture(tmp_path, [(name, b"x", mode)])
    budgets = _budgets(max_path_depth=4)
    stage = tmp_path / "stage"
    stage.mkdir()
    with pytest.raises(MaterializationError):
        manifest = _parse(archive, data, budgets)
        materialize_zip(archive, manifest, stage, budgets, started=__import__("time").monotonic())
    assert not (tmp_path / "escape").exists()


def test_duplicate_and_case_collision_rejected(tmp_path: Path) -> None:
    for names in (("source/a", "source/a"), ("source/a", "source/A")):
        archive, data = _fixture(
            tmp_path,
            [(name, b"x", stat.S_IFREG | 0o644) for name in names],
        )
        with pytest.raises(MaterializationError):
            _parse(archive, data, _budgets())


@pytest.mark.parametrize("mutation", ["missing", "unexpected", "size", "hash"])
def test_manifest_disagreement_never_publishes(tmp_path: Path, mutation: str) -> None:
    archive, data = _fixture(tmp_path, [("source/one", b"12345", stat.S_IFREG | 0o644)])
    document = json.loads(data)
    entry = document["entries"][0]
    if mutation == "missing":
        entry["path"] = "other"
    elif mutation == "unexpected":
        document["entries"].append(dict(entry, path="extra"))
        document["entry_count"] += 1
        document["total_uncompressed_bytes"] += 5
    elif mutation == "size":
        entry["size_bytes"] = 4
        document["total_uncompressed_bytes"] = 4
    else:
        entry["sha256"] = "b" * 64
    stage = tmp_path / "stage"
    stage.mkdir()
    with pytest.raises(MaterializationError):
        manifest = _parse(archive, json.dumps(document).encode(), _budgets())
        materialize_zip(
            archive, manifest, stage, _budgets(), started=__import__("time").monotonic()
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"max_materialized_bytes": 4},
        {"max_file_count": 1},
        {"max_preparation_write_bytes": 4},
        {"max_temporary_bytes": 4},
    ],
)
def test_budgets_reject_expansion(tmp_path: Path, changes: dict[str, int]) -> None:
    archive, data = _fixture(
        tmp_path,
        [
            ("source/one", b"12345", stat.S_IFREG | 0o644),
            ("source/two", b"6", stat.S_IFREG | 0o644),
        ],
    )
    budgets = _budgets(**changes)
    stage = tmp_path / "stage"
    stage.mkdir()
    with pytest.raises(MaterializationError):
        manifest = _parse(archive, data, budgets)
        materialize_zip(archive, manifest, stage, budgets, started=__import__("time").monotonic())
