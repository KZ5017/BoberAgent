"""Exact read-only mount description for the fixed D identity namespace.

This does not create a Python environment. E5-E must use the same selected
membership/pins and reject any expanded view, including excluded optional code.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

from .python_distribution import ManifestEntry, ProjectedDistributionManifest, Record

MOUNT_VERSION = "m20-e5-python-projection-mounts@1"


class ProjectionMount(Record):
    kind: Literal["DIRECTORY", "BIND", "SYMLINK"]
    path: str
    target: str | None = None


def _path(value: str) -> None:
    if len(value) > 2048 or any(
        re.fullmatch(r"[A-Za-z0-9_.+-]{1,255}", part) is None or part in {".", ".."}
        for part in value.split("/")
    ):
        raise ValueError("unsupported projection mount path")


def verify_exposure(
    manifest: ProjectedDistributionManifest,
    observed: tuple[ManifestEntry, ...],
) -> None:
    """A future publisher cannot certify extra bytes or interpret v1 as v2."""
    manifest = ProjectedDistributionManifest.model_validate_json(manifest.model_dump_json())
    if manifest.projection.profile.unsupported_optional != ("TKINTER_TCL_TK", "PACKAGE_MANAGER"):
        raise ValueError("historical projection cannot authorize current exposure")
    if tuple(sorted(observed, key=lambda e: e.path)) != manifest.entries:
        raise ValueError("runtime projection exposure mismatch")


def projection_mounts(manifest: ProjectedDistributionManifest) -> tuple[ProjectionMount, ...]:
    """Compress only complete selected subtrees; split every exclusion ancestor."""
    verify_exposure(manifest, manifest.entries)
    selected = {e.path: e for e in manifest.entries}
    excluded = tuple(e.entry.path for e in manifest.excluded_entries)
    result: list[ProjectionMount] = []
    covered: set[str] = set()
    for path, entry in sorted(selected.items(), key=lambda item: (item[0].count("/"), item[0])):
        _path(path)
        if any(path.startswith(parent + "/") for parent in covered):
            continue
        if entry.kind == "directory":
            if any(e.startswith(path + "/") for e in excluded):
                result.append(ProjectionMount(kind="DIRECTORY", path=path))
            else:
                result.append(ProjectionMount(kind="BIND", path=path))
                covered.add(path)
        elif entry.kind == "symlink":
            assert entry.target is not None
            # Source inventory already checked one-hop confinement. The native
            # descriptor accepts relative links only, never an absolute source.
            target = Path(os.path.normpath(Path(path).parent / entry.target)).as_posix()
            _path(target)
            if target not in selected or selected[target].kind != "file":
                raise ValueError("projection mount link target")
            result.append(ProjectionMount(kind="SYMLINK", path=path, target=entry.target))
        else:
            result.append(ProjectionMount(kind="BIND", path=path))
    # Check descriptor expansion rather than trusting compression alone.
    exposed = {
        e.path
        for e in manifest.entries
        if any(
            e.path == m.path or (m.kind == "BIND" and e.path.startswith(m.path + "/"))
            for m in result
        )
    }
    if exposed != set(selected) or any(
        e == m.path or (m.kind == "BIND" and e.startswith(m.path + "/"))
        for e in excluded
        for m in result
    ):
        raise ValueError("projection mount expansion mismatch")
    return tuple(result)


def mount_descriptor(manifest: ProjectedDistributionManifest) -> bytes:
    records = [MOUNT_VERSION, manifest.projection.projection_sha256]
    for mount in projection_mounts(manifest):
        if mount.target is not None and (
            len(mount.target) > 2048 or "\n" in mount.target or "\t" in mount.target
        ):
            raise ValueError("projection link syntax")
        records.append("\t".join((mount.kind, mount.path, mount.target or "-")))
    encoded = ("\n".join(records) + "\n").encode("ascii")
    # Fits the existing D operation's reserved temporary/control byte budget.
    if len(encoded) > 1024**2 or len(records) > 2048:
        raise ValueError("projection mount descriptor bound")
    return encoded


def write_mount_descriptor(path: Path, manifest: ProjectedDistributionManifest) -> None:
    data = mount_descriptor(manifest)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
