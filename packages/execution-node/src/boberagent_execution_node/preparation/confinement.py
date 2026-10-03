"""Closed, trusted Linux confinement preflight for E4; no acquired-code runner.

The proof is deliberately narrower than the E1/E5 subprocess requirement. E4 does
not run source or create a Python environment. Missing process/memory/storage limit
proof prevents E5 readiness and is never silently inferred from this preflight.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from boberagent_contracts.runtime_preparation import ConfinementFeature


class ConfinementUnavailable(RuntimeError):
    """The trusted host probe could not establish the E4 isolation baseline."""


class ConfinementFailure(StrEnum):
    """Bounded, non-sensitive reasons safe to return without subprocess stderr."""

    BACKEND_EXECUTABLE_UNAVAILABLE = "BACKEND_EXECUTABLE_UNAVAILABLE"
    UNSUPPORTED_HOST_TOPOLOGY = "UNSUPPORTED_HOST_TOPOLOGY"
    BACKEND_VERSION_PROBE_FAILED = "BACKEND_VERSION_PROBE_FAILED"
    BUBBLEWRAP_TRUSTED_PROBE_FAILED = "BUBBLEWRAP_TRUSTED_PROBE_FAILED"
    TRUSTED_EXECUTABLE_START_FAILED = "TRUSTED_EXECUTABLE_START_FAILED"
    NETWORK_ISOLATION_PROBE_FAILED = "NETWORK_ISOLATION_PROBE_FAILED"
    FILESYSTEM_ISOLATION_PROBE_FAILED = "FILESYSTEM_ISOLATION_PROBE_FAILED"


@dataclass(frozen=True)
class ConfinementProof:
    backend: str
    version: str
    features: tuple[ConfinementFeature, ...]


class ConfinementBackend(Protocol):
    def preflight(self) -> ConfinementProof: ...


E4_REQUIRED_FEATURES = (
    ConfinementFeature.NO_SUBPROCESS_NETWORK,
    ConfinementFeature.NO_INHERITED_SOCKETS,
    ConfinementFeature.NO_HOST_CONTROL_SOCKETS,
    ConfinementFeature.NO_ARBITRARY_HOST_FILESYSTEM,
)


_USRMERGE_LINKS = (
    ("bin", "usr/bin"),
    ("sbin", "usr/sbin"),
    ("lib", "usr/lib"),
    ("lib64", "usr/lib64"),
)


def _regular_directory(path: Path) -> bool:
    """Inspect the directory itself, never a symlink destination."""
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _trusted_runtime_mounts(host_root: Path) -> tuple[str, ...]:
    """Construct only known system mounts/links for a minimal bubblewrap root.

    ``host_root`` permits pure topology tests; production always passes ``/``.
    A compatibility link is recreated *inside* the namespace, not followed to
    another host location. Chains, absolute and noncanonical targets fail closed.
    """
    usr = host_root / "usr"
    if not _regular_directory(usr):
        raise ConfinementUnavailable(ConfinementFailure.UNSUPPORTED_HOST_TOPOLOGY)
    mounts = ["--ro-bind", str(usr), "/usr"]
    for name, expected in _USRMERGE_LINKS:
        path = host_root / name
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ConfinementUnavailable(ConfinementFailure.UNSUPPORTED_HOST_TOPOLOGY) from error
        if stat.S_ISDIR(mode):
            mounts.extend(("--ro-bind", str(path), f"/{name}"))
        elif stat.S_ISLNK(mode):
            try:
                target = os.readlink(path)
            except OSError as error:
                raise ConfinementUnavailable(
                    ConfinementFailure.UNSUPPORTED_HOST_TOPOLOGY
                ) from error
            if target != expected or not _regular_directory(host_root / expected):
                raise ConfinementUnavailable(ConfinementFailure.UNSUPPORTED_HOST_TOPOLOGY)
            mounts.extend(("--symlink", expected, f"/{name}"))
        else:
            raise ConfinementUnavailable(ConfinementFailure.UNSUPPORTED_HOST_TOPOLOGY)
    return tuple(mounts)


def _trusted_interpreter(host_root: Path) -> str:
    """Use the system Python inside /usr, never a venv/PATH-selected binary."""
    path = host_root / "usr/bin/python3"
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            # Debian/Kali's python3 -> python3.N link is the only supported hop.
            target = os.readlink(path)
            if not target.startswith("python3.") or not target[8:].isdigit():
                raise ConfinementUnavailable(ConfinementFailure.UNSUPPORTED_HOST_TOPOLOGY)
            path = path.parent / target
            mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or not mode & 0o111:
            raise ConfinementUnavailable(ConfinementFailure.UNSUPPORTED_HOST_TOPOLOGY)
    except OSError as error:
        raise ConfinementUnavailable(ConfinementFailure.UNSUPPORTED_HOST_TOPOLOGY) from error
    return "/usr/bin/python3"


def _probe_failure(returncode: int, stdout: bytes, stderr: bytes) -> ConfinementFailure | None:
    """Classify only closed-probe markers; never propagate raw subprocess output."""
    if returncode == 0 and stdout == b"E4_STARTED\nE4_CONFINED\n":
        return None
    if returncode == 21 and stdout == b"E4_STARTED\n":
        return ConfinementFailure.FILESYSTEM_ISOLATION_PROBE_FAILED
    if returncode == 22 and stdout == b"E4_STARTED\n":
        return ConfinementFailure.NETWORK_ISOLATION_PROBE_FAILED
    if b"bwrap: execvp " in stderr[:2048]:
        return ConfinementFailure.TRUSTED_EXECUTABLE_START_FAILED
    return ConfinementFailure.BUBBLEWRAP_TRUSTED_PROBE_FAILED


class BubblewrapConfinementBackend:
    """Probe a closed filesystem/network view; never accept caller argv or paths."""

    def preflight(self) -> ConfinementProof:
        if sys.platform != "linux":
            raise ConfinementUnavailable(ConfinementFailure.BACKEND_EXECUTABLE_UNAVAILABLE)
        executable = shutil.which("bwrap")
        if executable is None:
            raise ConfinementUnavailable(ConfinementFailure.BACKEND_EXECUTABLE_UNAVAILABLE)
        binds = _trusted_runtime_mounts(Path("/"))
        interpreter = _trusted_interpreter(Path("/"))
        try:
            version = subprocess.run(
                [executable, "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
                close_fds=True,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as error:
            raise ConfinementUnavailable(ConfinementFailure.BACKEND_VERSION_PROBE_FAILED) from error
        if not version.startswith("bubblewrap "):
            raise ConfinementUnavailable(ConfinementFailure.BACKEND_VERSION_PROBE_FAILED)
        with tempfile.TemporaryDirectory(prefix="boberagent-e4-probe-") as temporary:
            managed = Path(temporary)
            listener: socket.socket | None = None
            try:
                listener = socket.socket()
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
            except OSError as error:
                if listener is not None:
                    listener.close()
                raise ConfinementUnavailable(
                    ConfinementFailure.NETWORK_ISOLATION_PROBE_FAILED
                ) from error
            # No root bind, home, /etc, /run or ambient sockets are exposed.
            probe = f"""import pathlib, socket, sys
print('E4_STARTED', flush=True)
try:
    p = pathlib.Path('/work/probe')
    p.write_text('ok')
    assert p.read_text() == 'ok'
    assert not pathlib.Path('/run/docker.sock').exists()
    assert not pathlib.Path('/etc/passwd').exists()
except Exception:
    sys.exit(21)
try:
    s = socket.socket()
    s.settimeout(.2)
    assert s.connect_ex(('127.0.0.1', {listener.getsockname()[1]})) != 0
    s.close()
except Exception:
    sys.exit(22)
print('E4_CONFINED')
"""
            command = [
                executable,
                "--unshare-all",
                "--die-with-parent",
                "--new-session",
                "--clearenv",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                *binds,
                "--dir",
                "/work",
                "--bind",
                str(managed),
                "/work",
                "--setenv",
                "PATH",
                "/usr/bin:/bin",
                "--setenv",
                "HOME",
                "/nonexistent",
                "--chdir",
                "/work",
                interpreter,
                "-I",
                "-c",
                probe,
            ]
            try:
                child = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    close_fds=True,
                    start_new_session=True,
                    env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
                )
                try:
                    stdout, _stderr = child.communicate(timeout=5)
                except subprocess.TimeoutExpired as error:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.communicate()
                    raise ConfinementUnavailable(
                        ConfinementFailure.BUBBLEWRAP_TRUSTED_PROBE_FAILED
                    ) from error
            except OSError as error:
                raise ConfinementUnavailable(
                    ConfinementFailure.BUBBLEWRAP_TRUSTED_PROBE_FAILED
                ) from error
            finally:
                listener.close()
            if reason := _probe_failure(child.returncode, stdout, _stderr):
                raise ConfinementUnavailable(reason)
        return ConfinementProof("linux-bubblewrap", version, E4_REQUIRED_FEATURES)
