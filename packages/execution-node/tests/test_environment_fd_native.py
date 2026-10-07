"""Native inheritance + real Bubblewrap mechanics, NOT C/D/E Kali acceptance."""

import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest
from boberagent_execution_node.preparation import _environment_helper
from boberagent_execution_node.preparation.environment_models import EnvironmentManifest
from boberagent_execution_node.preparation.environment_storage import DIRECTORIES, FILES
from bubblewrap_contract import real_bubblewrap

# Fixed test-only driver uses the real reviewed constructor on local CPython.
# Relocation matches existing portable EnvBuilder tests, not D attestation.
# Inspect inheritable descriptors BEFORE importing the helper/opening any file.
DRIVER = """
import fcntl,importlib.util,os,stat,sys
assert stat.S_ISREG(os.fstat(3).st_mode)
assert fcntl.fcntl(3,fcntl.F_GETFD)==0
assert fcntl.fcntl(3,fcntl.F_GET_SEALS)==0
for fd in range(4,8192):
    try: os.fstat(fd)
    except OSError: continue
    raise AssertionError('unrelated descriptor survived')
spec=importlib.util.spec_from_file_location('trusted_helper','/trusted/environment.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
os.mkdir('/work/venv',0o700)
sys.prefix='/runtime'
helper.create()
"""


@pytest.fixture(scope="module")
def fd_handoff(tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("C toolchain required for native FD regression")
    binary = tmp_path_factory.mktemp("environment-fd") / "handoff"
    subprocess.run(
        [
            compiler,
            "-static",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-o",
            str(binary),
            str(Path(__file__).parent / "fixtures/environment_fd_test.c"),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return binary


@pytest.mark.parametrize("mode", ["same", "different", "verify"])
def test_native_dup_cloexec_and_default_deny(fd_handoff: Path, mode: str) -> None:
    result = subprocess.run([str(fd_handoff), mode], capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout == b""


def test_actual_bubblewrap_exports_fixed_environment_constructor(
    fd_handoff: Path, tmp_path: Path
) -> None:
    binary = real_bubblewrap()
    driver = tmp_path / "fixed-driver.py"
    driver.write_text(DRIVER)
    exported = tmp_path / "sealed-export"
    result = subprocess.run(
        [
            str(fd_handoff),
            "bubblewrap",
            str(binary),
            str(Path(_environment_helper.__file__)),
            str(driver),
            str(exported),
        ],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    data = exported.read_bytes()
    length = struct.unpack("!I", data[:4])[0]
    manifest = EnvironmentManifest.model_validate_json(data[4 : 4 + length])
    assert {entry.path for entry in manifest.entries} == DIRECTORIES | FILES | {"lib64"}
    assert manifest.written_bytes == sum(entry.size for entry in manifest.entries)
    assert len(data) == 4 + length + manifest.written_bytes
    assert json.loads(result.stdout)["export_bytes"] == len(data)
    assert not (tmp_path / "venv").exists()  # Namespace scratch, not a writable host bind.
