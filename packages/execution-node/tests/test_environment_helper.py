"""Actual trusted stdlib write interception; portable mechanics, NOT confinement."""

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from boberagent_execution_node.preparation import _environment_helper
from boberagent_execution_node.preparation.environment_models import EnvironmentManifest
from boberagent_execution_node.preparation.environment_storage import DIRECTORIES, FILES

# This test-only driver relocates scratch and uses the local interpreter solely
# to exercise CPython's real EnvBuilder/interception. No source/PoC is involved;
# it cannot supply D provenance, production namespace identity or readiness.
DRIVER = """
import importlib.util,os,sys
spec=importlib.util.spec_from_file_location('trusted_helper',sys.argv[1])
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
helper.PREFIX=sys.argv[2]
os.mkdir(helper.PREFIX,0o700)
fd=os.open(sys.argv[3],os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
os.dup2(fd,3)
if fd!=3: os.close(fd)
sys.prefix='/runtime'
if sys.argv[4]=='bytes': helper.WRITE_CAP=10
if sys.argv[4]=='inodes': helper.ENTRY_CAP=2
if sys.argv[4] in ('unaccounted','outside','socket','subprocess','fork','ensurepip'):
    sys.addaudithook(helper.audit)
    try:
        mode=sys.argv[4]
        if mode=='unaccounted': open(helper.PREFIX+'/bad','wb')
        elif mode=='outside': helper.accounted_open('/outside/bad','wb')
        elif mode=='socket': __import__('socket').socket()
        elif mode=='subprocess': __import__('subprocess').run([sys.executable,'-V'])
        elif mode=='fork': os.fork()
        elif mode=='ensurepip': __import__('ensurepip')
    except ValueError: sys.exit(17)
    sys.exit(0)
try: helper.create()
except ValueError as error:
    print(str(error),file=sys.stderr); sys.exit(17)
"""


def run(tmp_path: Path, mode: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-c",
            DRIVER,
            str(Path(_environment_helper.__file__)),
            str(tmp_path / "venv"),
            str(tmp_path / "export"),
            mode,
        ],
        capture_output=True,
        timeout=10,
        env={"LANG": "C", "PYTHONPATH": "/not-visible", "PYTHONUSERBASE": "/not-visible"},
    )


def test_actual_cpython_envbuilder_writes_are_accounted_without_pip(tmp_path: Path) -> None:
    result = run(tmp_path, "success")
    assert result.returncode == 0, result.stderr
    data = (tmp_path / "export").read_bytes()
    length = struct.unpack("!I", data[:4])[0]
    manifest = EnvironmentManifest.model_validate_json(data[4 : 4 + length])
    assert {entry.path for entry in manifest.entries} == DIRECTORIES | FILES | {"lib64"}
    assert manifest.written_bytes == sum(entry.size for entry in manifest.entries)
    assert manifest.created_entries == len(manifest.entries)
    assert len(data) == 4 + length + manifest.written_bytes
    assert json.loads(result.stdout)["export_bytes"] == len(data)
    assert list((tmp_path / "venv/lib/python3.12/site-packages").iterdir()) == []
    assert not any("pip" in entry.path or "ensurepip" in entry.path for entry in manifest.entries)
    assert not (tmp_path / "venv/__pycache__").exists()


@pytest.mark.parametrize(
    "mode",
    ["bytes", "inodes", "unaccounted", "outside", "socket", "subprocess", "fork", "ensurepip"],
)
def test_real_write_gate_denies_before_forbidden_action(tmp_path: Path, mode: str) -> None:
    result = run(tmp_path, mode)
    assert result.returncode == 17, result.stderr
    assert (tmp_path / "export").stat().st_size == 0
    assert not (tmp_path / "venv/bad").exists()


def test_control_export_is_regular_not_socket_or_host_mount() -> None:
    source = Path(_environment_helper.__file__).read_text()
    assert "os.write(3, view)" in source
    assert "with_pip=False" in source and "symlinks=False" in source
    assert "upgrade_deps=False" in source and "system_site_packages=False" in source
    assert os.path.isabs(_environment_helper.PREFIX)
