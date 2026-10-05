"""Bounded publisher of a CLOSED trusted venv layout, never an archive extractor."""

import hashlib
import os
import stat
import struct
from contextlib import suppress
from pathlib import Path

from boberagent_contracts import PythonEnvironmentInventory, PythonRuntimeBinding
from boberagent_contracts.python_runtime import RuntimeResourceRef

from .environment_models import (
    EXPORT_LIMIT,
    FILE_LIMIT,
    WRITE_LIMIT,
    EnvironmentEntry,
    EnvironmentManifest,
)
from .python_distribution import digest_value

DIRECTORIES = frozenset(
    {
        "bin",
        "include",
        "include/python3.12",
        "lib",
        "lib/python3.12",
        "lib/python3.12/site-packages",
    }
)
EXECUTABLES = frozenset({"bin/python", "bin/python3", "bin/python3.12"})
SCRIPTS = frozenset({"bin/activate", "bin/activate.csh", "bin/activate.fish", "bin/Activate.ps1"})
FILES = EXECUTABLES | SCRIPTS | {"pyvenv.cfg"}


def validate_layout(manifest: EnvironmentManifest) -> None:
    paths = [entry.path for entry in manifest.entries]
    if (
        paths != sorted(paths)
        or len(paths) != len(set(paths))
        or set(paths) != DIRECTORIES | FILES | {"lib64"}
        or manifest.created_entries != len(paths)
        or manifest.written_bytes != sum(entry.size for entry in manifest.entries)
        or manifest.written_bytes > WRITE_LIMIT
    ):
        raise ValueError("closed environment inventory mismatch")
    for entry in manifest.entries:
        if entry.path in DIRECTORIES:
            valid = (
                entry.kind == "directory"
                and entry.mode == 0o755
                and entry.size == 0
                and entry.sha256 is None
                and entry.target is None
            )
        elif entry.path == "lib64":
            valid = (
                entry.kind == "symlink"
                and entry.mode == 0o777
                and entry.size == 0
                and entry.target == "lib"
                and entry.sha256 is None
            )
        else:
            valid = (
                entry.kind == "file"
                and entry.mode == (0o755 if entry.path in EXECUTABLES else 0o644)
                and entry.sha256 is not None
                and entry.target is None
            )
        if not valid:
            raise ValueError("closed environment entry mismatch")


def _open_directory(path: Path) -> int:
    """No-follow traversal, including every ancestor; no directory-mode shortcuts."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("explicit owned storage required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = following
            info = os.fstat(fd)
            if (info.st_uid not in {0, os.getuid()} and not info.st_mode & stat.S_ISVTX) or (
                info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX
            ):
                raise ValueError("untrusted storage ancestor")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _relative_parent(root: int, path: str) -> tuple[int, str]:
    parts = path.split("/")
    # Membership is validated BEFORE this function: no general caller paths.
    fd = os.dup(root)
    try:
        for part in parts[:-1]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = following
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def _stable(info: os.stat_result) -> tuple[int, ...]:
    # Reads may legitimately update atime; content/ownership changes may not.
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


class EnvironmentStorage:
    """One exclusive Resource-owned workspace; retained failures are never overwritten."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def resource_directory(self, ref: RuntimeResourceRef) -> Path:
        return self.root / hashlib.sha256(str(ref).encode()).hexdigest()

    def initialize(self) -> None:
        parent = _open_directory(self.root.parent)
        try:
            with suppress(FileExistsError):
                os.mkdir(self.root.name, 0o700, dir_fd=parent)
            fd = os.open(
                self.root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
            )
            try:
                info = os.fstat(fd)
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise ValueError("private environment storage required")
            finally:
                os.close(fd)
        finally:
            os.close(parent)

    def reserve(self, ref: RuntimeResourceRef) -> Path:
        self.initialize()  # Only a held, budgeted constructor creates storage, not startup.
        parent = _open_directory(self.root)
        try:
            name = self.resource_directory(ref).name
            os.mkdir(name, 0o700, dir_fd=parent)
            os.fsync(parent)
        finally:
            os.close(parent)
        return self.resource_directory(ref)

    def publish(
        self, ref: RuntimeResourceRef, binding: PythonRuntimeBinding
    ) -> EnvironmentManifest:
        directory = self.resource_directory(ref)
        owner = _open_directory(directory)
        root = -1
        try:
            fd = os.open("export", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=owner)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_size > EXPORT_LIMIT
                ):
                    raise ValueError("export file bound")
                prefix = stream.read(4)
                if len(prefix) != 4 or not 1 <= (length := struct.unpack("!I", prefix)[0]) <= 65532:
                    raise ValueError("export framing")
                manifest = EnvironmentManifest.model_validate_json(stream.read(length))
                validate_layout(manifest)
                os.mkdir("publishing", 0o700, dir_fd=owner)
                root = os.open(
                    "publishing", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=owner
                )
                written = 0
                for entry in sorted(manifest.entries, key=lambda e: (e.path.count("/"), e.path)):
                    if entry.kind == "directory":
                        parent, name = _relative_parent(root, entry.path)
                        try:
                            os.mkdir(name, 0o755, dir_fd=parent)
                            os.chmod(name, 0o755, dir_fd=parent, follow_symlinks=False)
                        finally:
                            os.close(parent)
                # File stream order is manifest order, not parent-depth order.
                for entry in manifest.entries:
                    if entry.kind == "directory":
                        continue
                    parent, name = _relative_parent(root, entry.path)
                    try:
                        if entry.kind == "symlink":
                            os.symlink("lib", name, dir_fd=parent)
                            continue
                        fd = os.open(
                            name,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600,
                            dir_fd=parent,
                        )
                        with os.fdopen(fd, "wb") as output:
                            digest = hashlib.sha256()
                            remaining = entry.size
                            while remaining:
                                data = stream.read(min(65536, remaining))
                                if not data or written + len(data) > WRITE_LIMIT:
                                    raise ValueError("publication write bound")
                                output.write(data)
                                digest.update(data)
                                written += len(data)
                                remaining -= len(data)
                            if digest.hexdigest() != entry.sha256:
                                raise ValueError("publication content integrity")
                            output.flush()
                            os.fchmod(output.fileno(), entry.mode)
                            os.fsync(output.fileno())
                    finally:
                        os.close(parent)
                if stream.read(1) or written != manifest.written_bytes:
                    raise ValueError("export length mismatch")
            # Fsync every directory before a single owned atomic publication.
            for path in sorted(DIRECTORIES, key=lambda p: p.count("/"), reverse=True):
                parent, name = _relative_parent(root, path)
                try:
                    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    os.fsync(fd)
                    os.close(fd)
                finally:
                    os.close(parent)
            os.fsync(root)
            self.verify_tree(directory / "publishing", manifest, binding)
            os.rename("publishing", "venv", src_dir_fd=owner, dst_dir_fd=owner)
            os.fsync(owner)
            return manifest
        finally:
            if root >= 0:
                os.close(root)
            os.close(owner)

    def verify_tree(
        self, path: Path, manifest: EnvironmentManifest, binding: PythonRuntimeBinding
    ) -> PythonEnvironmentInventory:
        validate_layout(manifest)
        root = _open_directory(path)
        try:
            actual: list[EnvironmentEntry] = []
            config = b""

            def walk(fd: int, prefix: str = "") -> None:
                nonlocal config
                for name in sorted(os.listdir(fd)):
                    relative = prefix + name
                    if len(actual) >= FILE_LIMIT or relative not in DIRECTORIES | FILES | {"lib64"}:
                        raise ValueError("unexpected environment path")
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if info.st_uid != os.getuid():
                        raise ValueError("environment ownership")
                    mode = stat.S_IMODE(info.st_mode)
                    if stat.S_ISDIR(info.st_mode):
                        actual.append(
                            EnvironmentEntry(path=relative, kind="directory", mode=mode, size=0)
                        )
                        child = os.open(
                            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                        )
                        try:
                            walk(child, relative + "/")
                        finally:
                            os.close(child)
                    elif stat.S_ISLNK(info.st_mode):
                        if relative != "lib64" or os.readlink(name, dir_fd=fd) != "lib":
                            raise ValueError("unexpected environment link")
                        actual.append(
                            EnvironmentEntry(
                                path=relative, kind="symlink", mode=mode, size=0, target="lib"
                            )
                        )
                    elif (
                        stat.S_ISREG(info.st_mode)
                        and info.st_nlink == 1
                        and info.st_size <= WRITE_LIMIT
                    ):
                        child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                        with os.fdopen(child, "rb") as stream:
                            if _stable(os.fstat(stream.fileno())) != _stable(info):
                                raise ValueError("environment changed")
                            digest = hashlib.file_digest(stream, "sha256").hexdigest()
                            if _stable(os.fstat(stream.fileno())) != _stable(info):
                                raise ValueError("environment changed")
                            if relative == "pyvenv.cfg":
                                stream.seek(0)
                                config = stream.read(4097)
                        actual.append(
                            EnvironmentEntry(
                                path=relative,
                                kind="file",
                                mode=mode,
                                size=info.st_size,
                                sha256=digest,
                            )
                        )
                    else:
                        raise ValueError("unexpected filesystem object")

            walk(root)
            if tuple(sorted(actual, key=lambda e: e.path)) != manifest.entries:
                raise ValueError("retained environment integrity")
            expected_config = {
                "home": "/runtime/bin",
                "include-system-site-packages": "false",
                "version": binding.interpreter.summary.python_version,
                "executable": "/runtime/bin/python3.12",
                "command": "/runtime/bin/python3.12 -m venv --copies --without-pip /work/venv",
            }
            fields = dict(line.split(" = ", 1) for line in config.decode("utf-8").splitlines())
            if (
                len(config) > 4096
                or fields != expected_config
                or len(fields) != len(config.splitlines())
            ):
                raise ValueError("venv configuration mismatch")
            files = {entry.path: entry for entry in manifest.entries}
            for executable in EXECUTABLES:
                if files[executable].sha256 != binding.interpreter.summary.executable_sha256:
                    raise ValueError("copied interpreter mismatch")
            return PythonEnvironmentInventory(
                namespace_prefix="/work/venv",
                pyvenv_config_sha256=hashlib.sha256(config).hexdigest(),
                inventory_sha256=digest_value(manifest.entries),
                file_count=len(manifest.entries),
                total_bytes=manifest.written_bytes,
                copied_executable_sha256=binding.interpreter.summary.executable_sha256,
                permitted_links=("lib64->lib",),
                system_site_packages=False,
                pip_bootstrapped=False,
                pip_used=False,
            )
        finally:
            os.close(root)
