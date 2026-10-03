"""Trusted E4 host preflight; real bubblewrap is optional in portable CI."""

import shutil
import socket
import sys
from pathlib import Path

import pytest
from boberagent_contracts.runtime_preparation import ConfinementFeature
from boberagent_execution_node.preparation.confinement import (
    BubblewrapConfinementBackend,
    ConfinementFailure,
    ConfinementUnavailable,
    _probe_failure,
    _trusted_interpreter,
    _trusted_runtime_mounts,
)


def test_absent_backend_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(ConfinementUnavailable, match="BACKEND_EXECUTABLE_UNAVAILABLE"):
        BubblewrapConfinementBackend().preflight()


def test_binary_presence_without_namespace_probe_does_not_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class StubListener:
        def bind(self, _address: tuple[str, int]) -> None: ...

        def listen(self, _backlog: int) -> None: ...

        def getsockname(self) -> tuple[str, int]:
            return ("127.0.0.1", 19001)

        def close(self) -> None: ...

    fake = tmp_path / "bwrap"
    fake.write_text(
        "#!/bin/sh\nif [ \"$1\" = --version ]; then echo 'bubblewrap 0.11.0'; else exit 1; fi\n"
    )
    fake.chmod(0o700)
    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name: str(fake) if name == "bwrap" else real_which(name)
    )
    monkeypatch.setattr(socket, "socket", StubListener)
    with pytest.raises(ConfinementUnavailable, match="BUBBLEWRAP_TRUSTED_PROBE_FAILED"):
        BubblewrapConfinementBackend().preflight()


def _usrmerge_root(root: Path) -> None:
    for directory in ("bin", "sbin", "lib", "lib64"):
        (root / "usr" / directory).mkdir(parents=True)
        (root / directory).symlink_to(f"usr/{directory}")
    python = root / "usr/bin/python3.13"
    python.write_bytes(b"trusted fixture executable")
    python.chmod(0o755)
    (root / "usr/bin/python3").symlink_to("python3.13")


def test_usrmerge_compatibility_links_preserve_loader_topology(tmp_path: Path) -> None:
    _usrmerge_root(tmp_path)
    # The dynamic loader's absolute /lib64 path must resolve to the exposed
    # /usr/lib64 tree, without binding any other host directory or host root.
    (tmp_path / "usr/lib64/ld-linux-x86-64.so.2").write_bytes(b"loader fixture")
    mounts = _trusted_runtime_mounts(tmp_path)
    assert mounts == (
        "--ro-bind",
        str(tmp_path / "usr"),
        "/usr",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/sbin",
        "/sbin",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
    )
    assert _trusted_interpreter(tmp_path) == "/usr/bin/python3"
    assert ("--ro-bind", str(tmp_path), "/") not in tuple(
        mounts[index : index + 3] for index in range(len(mounts) - 2)
    )


@pytest.mark.parametrize(
    "bad_target",
    ["/tmp/foo", "/home/user/bin", "../../unexpected", "usr/other", "usr/bin/../bin"],
)
def test_unexpected_compatibility_links_fail_closed(tmp_path: Path, bad_target: str) -> None:
    _usrmerge_root(tmp_path)
    (tmp_path / "lib64").unlink()
    (tmp_path / "lib64").symlink_to(bad_target)
    with pytest.raises(ConfinementUnavailable, match="UNSUPPORTED_HOST_TOPOLOGY"):
        _trusted_runtime_mounts(tmp_path)


def test_compatibility_target_must_be_real_directory_not_symlink_chain(tmp_path: Path) -> None:
    _usrmerge_root(tmp_path)
    (tmp_path / "usr/lib64").rmdir()
    (tmp_path / "usr/lib64").symlink_to("lib")
    with pytest.raises(ConfinementUnavailable, match="UNSUPPORTED_HOST_TOPOLOGY"):
        _trusted_runtime_mounts(tmp_path)


def test_missing_compatibility_target_fails_closed(tmp_path: Path) -> None:
    _usrmerge_root(tmp_path)
    (tmp_path / "usr/lib64").rmdir()
    with pytest.raises(ConfinementUnavailable, match="UNSUPPORTED_HOST_TOPOLOGY"):
        _trusted_runtime_mounts(tmp_path)


def test_real_compatibility_directory_is_read_only(tmp_path: Path) -> None:
    _usrmerge_root(tmp_path)
    (tmp_path / "lib64").unlink()
    (tmp_path / "lib64").mkdir()
    mounts = _trusted_runtime_mounts(tmp_path)
    assert ("--ro-bind", str(tmp_path / "lib64"), "/lib64") in tuple(
        mounts[index : index + 3] for index in range(len(mounts) - 2)
    )


def test_interpreter_symlink_cannot_escape_trusted_usr_bin(tmp_path: Path) -> None:
    _usrmerge_root(tmp_path)
    (tmp_path / "usr/bin/python3").unlink()
    (tmp_path / "usr/bin/python3").symlink_to("/tmp/python3")
    with pytest.raises(ConfinementUnavailable, match="UNSUPPORTED_HOST_TOPOLOGY"):
        _trusted_interpreter(tmp_path)


def test_diagnostic_codes_are_bounded_and_non_sensitive() -> None:
    assert ConfinementFailure.UNSUPPORTED_HOST_TOPOLOGY.value == "UNSUPPORTED_HOST_TOPOLOGY"
    assert all(len(reason.value) <= 128 for reason in ConfinementFailure)
    assert _probe_failure(0, b"E4_STARTED\nE4_CONFINED\n", b"") is None
    assert _probe_failure(21, b"E4_STARTED\n", b"") == (
        ConfinementFailure.FILESYSTEM_ISOLATION_PROBE_FAILED
    )
    assert _probe_failure(22, b"E4_STARTED\n", b"") == (
        ConfinementFailure.NETWORK_ISOLATION_PROBE_FAILED
    )
    assert _probe_failure(1, b"", b"bwrap: execvp /usr/bin/python3: missing") == (
        ConfinementFailure.TRUSTED_EXECUTABLE_START_FAILED
    )
    assert _probe_failure(1, b"", b"private host detail") == (
        ConfinementFailure.BUBBLEWRAP_TRUSTED_PROBE_FAILED
    )


def test_real_linux_bubblewrap_closed_probe_when_available() -> None:
    if sys.platform != "linux" or shutil.which("bwrap") is None:
        pytest.skip("real Linux bubblewrap is not installed in this test environment")
    try:
        proof = BubblewrapConfinementBackend().preflight()
    except ConfinementUnavailable as error:
        pytest.skip(f"host does not permit required rootless bubblewrap probe: {error}")
    assert proof.backend == "linux-bubblewrap"
    assert proof.version.startswith("bubblewrap ")
    assert ConfinementFeature.NO_SUBPROCESS_NETWORK in proof.features
    assert ConfinementFeature.NO_ARBITRARY_HOST_FILESYSTEM in proof.features
    # E4 does not infer future E5 process/memory/storage guarantees from this probe.
    assert ConfinementFeature.MEMORY_LIMIT not in proof.features
    assert ConfinementFeature.PROCESS_LIMIT not in proof.features
    assert ConfinementFeature.STORAGE_LIMIT not in proof.features
