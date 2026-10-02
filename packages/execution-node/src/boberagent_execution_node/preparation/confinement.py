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
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from boberagent_contracts.runtime_preparation import ConfinementFeature


class ConfinementUnavailable(RuntimeError):
    """The trusted host probe could not establish the E4 isolation baseline."""


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


class BubblewrapConfinementBackend:
    """Probe a closed filesystem/network view; never accept caller argv or paths."""

    def preflight(self) -> ConfinementProof:
        if sys.platform != "linux":
            raise ConfinementUnavailable("CONFINEMENT_UNAVAILABLE")
        executable = shutil.which("bwrap")
        interpreter = shutil.which("python3")
        if executable is None or interpreter is None:
            raise ConfinementUnavailable("CONFINEMENT_UNAVAILABLE")
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
            raise ConfinementUnavailable("CONFINEMENT_PROBE_FAILED") from error
        if not version.startswith("bubblewrap "):
            raise ConfinementUnavailable("CONFINEMENT_PROBE_FAILED")
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
                raise ConfinementUnavailable("CONFINEMENT_PROBE_FAILED") from error
            # No root bind, home, /etc, /run or ambient sockets are exposed.
            binds: list[str] = []
            for directory in ("/usr", "/lib", "/lib64", "/bin"):
                if Path(directory).is_dir() and not Path(directory).is_symlink():
                    binds.extend(("--ro-bind", directory, directory))
            if not Path(interpreter).resolve().is_relative_to(Path("/usr")):
                listener.close()
                raise ConfinementUnavailable("CONFINEMENT_UNAVAILABLE")
            probe = (
                "import os,socket,pathlib; "
                "p=pathlib.Path('/work/probe'); p.write_text('ok'); "
                "assert p.read_text()=='ok'; "
                "assert not pathlib.Path('/run/docker.sock').exists(); "
                "assert not pathlib.Path('/etc/passwd').exists(); "
                "s=socket.socket(); s.settimeout(.2); "
                f"assert s.connect_ex(('127.0.0.1', {listener.getsockname()[1]}))!=0; "
                "s.close(); "
                "print('E4_CONFINED')"
            )
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
                    raise ConfinementUnavailable("CONFINEMENT_PROBE_FAILED") from error
            except OSError as error:
                raise ConfinementUnavailable("CONFINEMENT_PROBE_FAILED") from error
            finally:
                listener.close()
            if child.returncode != 0 or stdout != b"E4_CONFINED\n":
                raise ConfinementUnavailable("CONFINEMENT_PROBE_FAILED")
        return ConfinementProof("linux-bubblewrap", version, E4_REQUIRED_FEATURES)
