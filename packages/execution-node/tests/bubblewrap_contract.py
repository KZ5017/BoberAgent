"""Real CLI test utility; never downloads tools or supplies production readiness."""

import fcntl
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def real_bubblewrap() -> Path:
    configured = os.environ.get("BOBERAGENT_E5_BWRAP")
    candidate = configured or shutil.which("bwrap")
    if candidate is None:
        pytest.skip("Real Bubblewrap CLI required; set BOBERAGENT_E5_BWRAP explicitly")
    path = Path(candidate)
    assert path.is_file(), "Configured Bubblewrap missing"
    expected = os.environ.get("BOBERAGENT_E5_BWRAP_SHA256")
    if expected is not None:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    return path


def parse_options(binary: Path, data: bytes) -> subprocess.CompletedProcess[bytes]:
    # Real parse_args_recurse validates the sealed options BEFORE --help exits.
    # No namespace, mount, command or fixture paths are touched by this probe.
    fd = os.memfd_create("bubblewrap-options-contract", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        os.write(fd, data)
        os.lseek(fd, 0, os.SEEK_SET)
        fcntl.fcntl(
            fd,
            fcntl.F_ADD_SEALS,
            fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL,
        )
        return subprocess.run(
            [str(binary), "--args", str(fd), "--help"],
            pass_fds=(fd,),
            capture_output=True,
            timeout=5,
            check=False,
        )
    finally:
        os.close(fd)
