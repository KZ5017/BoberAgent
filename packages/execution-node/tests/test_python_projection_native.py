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
from bubblewrap_contract import parse_options, real_bubblewrap
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


def command_remainder(arguments: list[str], fd_options: list[str]) -> list[str]:
    """Critical bubblewrap 0.11.0 parse_args_recurse semantics, no namespaces.

    The recursive argument-file remainder is discarded. Only the outer remainder
    becomes COMMAND/ARGS. Option operands must not be mistaken for a command.
    """
    arities = {
        "--unshare-all": 0,
        "--die-with-parent": 0,
        "--new-session": 0,
        "--clearenv": 0,
        "--uid": 1,
        "--gid": 1,
        "--cap-drop": 1,
        "--cap-add": 1,
        "--proc": 1,
        "--remount-ro": 1,
        "--dir": 1,
        "--ro-bind": 2,
        "--symlink": 2,
        "--chdir": 1,
    }
    offset = 0
    while offset < len(arguments):
        option = arguments[offset]
        if option == "--args":
            assert offset + 1 < len(arguments)
            command_remainder(fd_options, [])  # Recursive remainder is NOT copied out.
            offset += 2
        elif option == "--":
            return arguments[offset + 1 :]
        elif not option.startswith("--"):
            return arguments[offset:]
        else:
            arity = arities[option]
            assert offset + arity < len(arguments)
            offset += arity + 1
    return []


def test_fixed_identity_launch_keeps_command_outside_sealed_options(
    configured: PythonDistributionConfiguration,
    descriptor_parser: Path,
    tmp_path: Path,
) -> None:
    install_feature(configured)
    manifest = inventory(repin(configured))
    descriptor = tmp_path / "mounts"
    write_mount_descriptor(descriptor, manifest)
    result = subprocess.run(
        [
            str(descriptor_parser),
            str(descriptor),
            str(configured.distribution_root),
            str(configured.system_library_root / "ld-linux-x86-64.so.2"),
        ],
        check=True,
        capture_output=True,
        timeout=5,
    )
    outer_bytes, fd_bytes = result.stdout.split(b"\0\0", 1)
    outer = outer_bytes.decode().split("\0")
    options = fd_bytes.decode().removesuffix("\0").split("\0")
    assert outer[:2] == ["/trusted/bwrap-test", "--args"]
    assert outer[2].isdigit()
    assert outer[3:] == ["--", "/trusted/helper", "identity-fixture"]
    assert options[-2:] == ["--chdir", "/work"]
    assert "identity-fixture" not in options
    # This occurrence is required as a mount destination, NOT as COMMAND.
    target = options.index("/trusted/helper")
    assert options[target - 2 : target] == ["--ro-bind", "/trusted/helper-test"]
    assert options.count("/trusted/helper") == 1
    assert not command_remainder(options, [])
    assert command_remainder(outer[1:], options) == ["/trusted/helper", "identity-fixture"]
    assert len(options) <= 8500 and len(fd_bytes) <= 2 * 1024**2
    assert "libtcl" not in fd_bytes.decode() and "site-packages" not in fd_bytes.decode()
    assert b"/runtime/lib\0" in fd_bytes
    assert "--ro-bind" in options and "--unshare-all" in options


def test_parser_semantics_reproduce_original_missing_outer_command() -> None:
    options = ["--chdir", "/work"]
    recursive = [*options, "/trusted/helper", "identity-fixture"]
    assert command_remainder(recursive, []) == ["/trusted/helper", "identity-fixture"]
    # Recursive remainder is ignored in the real parser, never copied out.
    assert command_remainder(["--args", "3"], recursive) == []
    assert command_remainder(
        ["--args", "3", "--", "/trusted/helper", "identity-fixture"], options
    ) == ["/trusted/helper", "identity-fixture"]


@pytest.mark.parametrize("operation", ["create", "verify"])
def test_environment_launch_preserves_projection_and_fixed_outer_command(
    configured: PythonDistributionConfiguration,
    descriptor_parser: Path,
    tmp_path: Path,
    operation: str,
) -> None:
    install_feature(configured)
    manifest = inventory(repin(configured))
    descriptor = tmp_path / "mounts-e"
    write_mount_descriptor(descriptor, manifest)
    result = subprocess.run(
        [
            str(descriptor_parser),
            "--environment-" + operation,
            str(descriptor),
            str(configured.distribution_root),
            str(configured.system_library_root / "ld-linux-x86-64.so.2"),
            "/private/resource/venv",
        ],
        check=True,
        capture_output=True,
        timeout=5,
    )
    outer_bytes, fd_bytes = result.stdout.split(b"\0\0", 1)
    outer = outer_bytes.decode().split("\0")
    options = fd_bytes.decode().removesuffix("\0").split("\0")
    assert command_remainder(outer[1:], options) == [
        "/trusted/helper",
        "environment-" + operation + "-fixture",
    ]
    assert not command_remainder(options, [])
    assert options[
        options.index("/trusted/provider/environment.py") - 1 : options.index(
            "/trusted/provider/environment.py"
        )
        + 2
    ] == ["--ro-bind", "/trusted/provider/environment.py", "/trusted/environment.py"]
    assert "site-packages" not in fd_bytes.decode() and "tkinter" not in fd_bytes.decode()
    assert "--bind" not in options and "/source" not in options
    assert "--preserve-fds" not in options and "--sync-fd" not in options
    if operation == "verify":
        index = options.index("/private/resource/venv")
        assert options[index - 1 : index + 2] == [
            "--ro-bind",
            "/private/resource/venv",
            "/work/venv",
        ]
    else:
        assert "/private/resource/venv" not in options


@pytest.mark.parametrize("operation", ["identity", "create", "verify"])
def test_native_options_are_accepted_by_real_bubblewrap_parser(
    configured: PythonDistributionConfiguration,
    descriptor_parser: Path,
    tmp_path: Path,
    operation: str,
) -> None:
    binary = real_bubblewrap()
    install_feature(configured)
    descriptor = tmp_path / "real-cli-mounts"
    write_mount_descriptor(descriptor, inventory(repin(configured)))
    arguments = [
        str(descriptor),
        str(configured.distribution_root),
        str(configured.system_library_root / "ld-linux-x86-64.so.2"),
    ]
    if operation != "identity":
        arguments = ["--environment-" + operation, *arguments, "/private/resource/venv"]
    captured = subprocess.run(
        [str(descriptor_parser), *arguments], check=True, capture_output=True, timeout=5
    )
    _, options = captured.stdout.split(b"\0\0", 1)
    assert b"--preserve-fds\0" not in options and b"--sync-fd\0" not in options
    parsed = parse_options(binary, options)
    assert parsed.returncode == 0, parsed.stderr
    # Prove this is the actual parser, not a mock silently accepting any argv.
    invalid = parse_options(binary, b"--preserve-fds\0" + b"1\0" + options)
    assert invalid.returncode != 0 and b"Unknown option --preserve-fds" in invalid.stderr


@pytest.mark.parametrize("bound", ["count", "length", "byte"])
def test_native_argument_writer_bounds_still_fail_closed(
    descriptor_parser: Path, bound: str
) -> None:
    result = subprocess.run(
        [str(descriptor_parser), f"--{bound}-limit"], capture_output=True, timeout=5
    )
    assert result.returncode == 90 and result.stdout == b""


@pytest.mark.parametrize(
    "record", ["BIND\t../host\t-", "BIND\t--command\t-", "BIND\tlib\t-\tidentity-fixture"]
)
def test_identity_launch_cannot_accept_command_from_projection_descriptor(
    descriptor_parser: Path, tmp_path: Path, record: str
) -> None:
    descriptor = tmp_path / "mounts"
    descriptor.write_text("m20-e5-python-projection-mounts@1\n" + "a" * 64 + "\n" + record + "\n")
    descriptor.chmod(0o600)
    result = subprocess.run(
        [str(descriptor_parser), str(descriptor), str(tmp_path), "/trusted/ld-linux-x86-64.so.2"],
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 90 and result.stdout == b""
