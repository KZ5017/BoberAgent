"""Production bounded export mechanics only; never real cgroup/Kali acceptance."""

import shutil
import subprocess
from pathlib import Path

import pytest


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
