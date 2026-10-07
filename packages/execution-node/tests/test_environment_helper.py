"""Actual trusted stdlib write interception; portable mechanics, NOT confinement."""

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from boberagent_execution_node.preparation import _environment_helper
from boberagent_execution_node.preparation.environment_models import (
    WRITE_LIMIT,
    EnvironmentManifest,
)
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
if sys.argv[4]=='large':
    source=sys.argv[5]
    fd=os.open(source,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o755)
    os.ftruncate(fd,30913848);os.close(fd)
    sys._base_executable=source
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
if sys.argv[4]=='large':
    # Test the production write gate at its exact fixed bound after construction.
    # No monkeypatch of charge()/WRITE_CAP/copy_file or byte accounting.
    remaining=helper.WRITE_CAP-helper.written_bytes
    block=b'x'*65536
    with helper.accounted_open(helper.PREFIX+'/budget-tail','wb') as output:
        while remaining:
            part=block[:min(remaining,len(block))]
            output.write(part);remaining-=len(part)
        position=output.tell()
        try: output.write(b'x')
        except ValueError:
            assert output.tell()==position
            assert helper.written_bytes==helper.WRITE_CAP
        else: raise AssertionError('over-limit write accepted')
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
            str(tmp_path / "python3.12"),
        ],
        capture_output=True,
        timeout=30,
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


def test_real_envbuilder_accounts_three_supported_size_copies_and_fails_over_limit(
    tmp_path: Path,
) -> None:
    # Sparse test source, deterministic size independent of the host launcher.
    # EnvBuilder copies its contents but NEVER executes this synthetic file.
    result = run(tmp_path, "large")
    assert result.returncode == 0, result.stderr
    data = (tmp_path / "export").read_bytes()
    length = struct.unpack("!I", data[:4])[0]
    manifest = EnvironmentManifest.model_validate_json(data[4 : 4 + length])
    executables = {
        entry.path: entry for entry in manifest.entries if entry.path.startswith("bin/python")
    }
    assert set(executables) == {"bin/python", "bin/python3", "bin/python3.12"}
    assert {entry.size for entry in executables.values()} == {30_913_848}
    assert len({entry.sha256 for entry in executables.values()}) == 1
    assert manifest.written_bytes == sum(entry.size for entry in manifest.entries)
    assert 3 * 30_913_848 < manifest.written_bytes < WRITE_LIMIT
    assert json.loads(result.stdout)["written_bytes"] == manifest.written_bytes
    assert len(data) == 4 + length + manifest.written_bytes
    assert (tmp_path / "venv/budget-tail").stat().st_size == WRITE_LIMIT - manifest.written_bytes


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
