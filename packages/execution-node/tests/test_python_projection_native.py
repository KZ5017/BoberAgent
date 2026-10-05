"""Production native descriptor parsing only; no interpreter/kernel acceptance."""

import shutil
import subprocess
from pathlib import Path

import pytest
from boberagent_execution_node.preparation.python_distribution import (
    PythonDistributionConfiguration,
    inventory,
)
from boberagent_execution_node.preparation.python_projection import (
    projection_mounts,
    write_mount_descriptor,
)
from test_python_projection import install_feature
from test_python_provenance import configured as configured
from test_python_provenance import repin


@pytest.fixture
def descriptor_parser(tmp_path: Path) -> Path:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("Linux C toolchain required for static formatter test")
    binary = tmp_path / "descriptor-parser"
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
            str(Path(__file__).parent / "fixtures/projection_descriptor_test.c"),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return binary


def test_native_mount_arguments_exactly_match_certified_projection(
    configured: PythonDistributionConfiguration,
    descriptor_parser: Path,
    tmp_path: Path,
) -> None:
    install_feature(configured)
    manifest = inventory(repin(configured))
    descriptor = tmp_path / "mounts"
    write_mount_descriptor(descriptor, manifest)
    expected: list[str] = []
    for mount in projection_mounts(manifest):
        target = "/runtime/" + mount.path
        if mount.kind == "DIRECTORY":
            expected.extend(("--dir", target))
        elif mount.kind == "SYMLINK":
            assert mount.target is not None
            expected.extend(("--symlink", mount.target, target))
        else:
            expected.extend(("--ro-bind", str(configured.distribution_root / mount.path), target))
    parsed = subprocess.run(
        [str(descriptor_parser), str(descriptor), str(configured.distribution_root)],
        check=True,
        capture_output=True,
        timeout=5,
    )
    assert parsed.stdout == b"".join(value.encode() + b"\0" for value in expected)
    assert b"libtcl" not in parsed.stdout and b"tkinter" not in parsed.stdout
    assert b"/runtime/lib\0" in parsed.stdout  # directory only, not whole-lib bind


@pytest.mark.parametrize(
    "records",
    [
        "BIND\t../outside\t-",
        "BIND\t/absolute\t-",
        "BIND\tbin//python\t-",
        "BIND\tlib/../../host\t-",
        "SYMLINK\tlib/link\t../../host",
        "SYMLINK\tlib/link\t/host",
        "UNKNOWN\tlib\t-",
        "BIND\tlib\t--extra",
        "BIND\tlib\t-\t--ro-bind",
        "BIND\tlib\t-\0junk",
        "BIND\tetc\t-",
    ],
)
def test_native_parser_rejects_unsafe_mount_syntax(
    descriptor_parser: Path,
    tmp_path: Path,
    records: str,
) -> None:
    descriptor = tmp_path / "mounts"
    descriptor.write_text("m20-e5-python-projection-mounts@1\n" + "a" * 64 + "\n" + records + "\n")
    descriptor.chmod(0o600)
    rejected = subprocess.run(
        [str(descriptor_parser), str(descriptor), str(tmp_path)], capture_output=True, timeout=5
    )
    assert rejected.returncode == 90 and rejected.stdout == b""


def test_native_parser_requires_private_regular_descriptor(
    descriptor_parser: Path, tmp_path: Path
) -> None:
    descriptor = tmp_path / "mounts"
    descriptor.write_text("m20-e5-python-projection-mounts@1\n" + "a" * 64 + "\nBIND\tbin\t-\n")
    descriptor.chmod(0o644)
    assert (
        subprocess.run(
            [str(descriptor_parser), str(descriptor), str(tmp_path)], capture_output=True, timeout=5
        ).returncode
        == 90
    )
    descriptor.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(descriptor)
    assert (
        subprocess.run(
            [str(descriptor_parser), str(link), str(tmp_path)], capture_output=True, timeout=5
        ).returncode
        == 90
    )
