"""Production bounded export mechanics only; never real cgroup/Kali acceptance."""

import shutil
import subprocess
from pathlib import Path

import pytest
from boberagent_execution_node.preparation.environment_limits import (
    EXPORT_LIMIT,
    FILE_LIMIT,
    MEMORY_LIMIT,
    SCRATCH_LIMIT,
    WRITE_LIMIT,
)
from bubblewrap_contract import real_bubblewrap


@pytest.fixture(scope="module")
def exporter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("C toolchain required for native export test")
    binary = tmp_path_factory.mktemp("export-native") / "exporter"
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
            str(Path(__file__).parent / "fixtures/environment_export_test.c"),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return binary


@pytest.mark.parametrize(
    "mode", ["success", "oversize", "short", "expired", "owner-lost", "wrong-sink"]
)
def test_native_export_seals_and_bounds_with_owner_liveness(exporter: Path, mode: str) -> None:
    result = subprocess.run([str(exporter), mode], capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout == b""  # Artifact bytes are never ordinary helper stdout.


def test_compiled_native_capacities_match_fixed_provider_contract(exporter: Path) -> None:
    result = subprocess.run([str(exporter), "limits"], check=True, capture_output=True, timeout=5)
    assert tuple(map(int, result.stdout.split())) == (
        WRITE_LIMIT,
        EXPORT_LIMIT,
        SCRATCH_LIMIT,
        MEMORY_LIMIT,
        FILE_LIMIT,
    )


def test_real_bubblewrap_production_tmpfs_holds_maximum_accepted_payload(tmp_path: Path) -> None:
    bwrap = real_bubblewrap()
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("C toolchain required for native scratch capacity test")
    binary = tmp_path / "scratch-proof"
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
            str(Path(__file__).parent / "fixtures/environment_scratch_test.c"),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    result = subprocess.run([str(binary), str(bwrap)], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert tuple(map(int, result.stdout.split())) == (WRITE_LIMIT, SCRATCH_LIMIT, FILE_LIMIT)
    assert not (tmp_path / "capacity").exists()
