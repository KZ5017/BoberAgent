"""Owner-bound static DT_NEEDED closure; all ELF bytes are synthetic/inert."""

import hashlib
import os
import struct
from pathlib import Path

import pytest
from boberagent_contracts import PythonRuntimeReason
from boberagent_execution_node.preparation import python_distribution as distribution
from boberagent_execution_node.preparation.python_distribution import (
    ProvenanceFailure,
    PythonDistributionConfiguration,
    _DependencyKind,
    _elf,
    inventory,
)
from test_python_provenance import configured as configured
from test_python_provenance import elf


def needed_elf(*names: str) -> bytes:
    """Real libpython3.so string-table address/size class, not a real binary."""
    strings = b"".join(name.encode("ascii") + b"\0" for name in names)
    table_size = max(206, len(strings))
    data = bytearray(0x5000 + table_size)
    data[:512] = elf()
    struct.pack_into("<HH", data, 54, 56, 2)
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 4, 0, 0, 0, len(data), len(data), 4096)
    dynamic_size = (len(names) + 3) * 16
    struct.pack_into("<IIQQQQQQ", data, 120, 2, 4, 256, 256, 0, dynamic_size, dynamic_size, 8)
    dynamic = [(5, 0x5000), (10, table_size)]
    offset = 0
    for name in names:
        dynamic.append((1, offset))
        offset += len(name) + 1
    dynamic.append((0, 0))
    for index, pair in enumerate(dynamic):
        struct.pack_into("<qQ", data, 256 + index * 16, *pair)
    data[0x5000 : 0x5000 + len(strings)] = strings
    return bytes(data)


@pytest.mark.parametrize("token", ["$ORIGIN", "${ORIGIN}"])
def test_parser_returns_typed_owner_bound_internal_and_bare_dependencies(token: str) -> None:
    owner = Path("/runtime/lib/libpython3.so")
    dependencies, loader = _elf(
        needed_elf(f"{token}/../lib/libpython3.12.so.1.0", "libpthread.so.0", "libc.so.6"),
        owner=owner,
        boundary=Path("/runtime"),
    )
    assert loader is None
    assert dependencies[0].owner == owner
    assert dependencies[0].raw == f"{token}/../lib/libpython3.12.so.1.0"
    assert dependencies[0].kind is _DependencyKind.PATH_DEPENDENCY
    assert dependencies[0].resolved == Path("/runtime/lib/libpython3.12.so.1.0")
    assert [d.raw for d in dependencies[1:]] == ["libpthread.so.0", "libc.so.6"]
    assert all(
        d.kind is _DependencyKind.BARE_SONAME and d.resolved is None for d in dependencies[1:]
    )
    assert all(d.owner == owner for d in dependencies)


@pytest.mark.parametrize("token", ["$ORIGIN", "${ORIGIN}"])
def test_nested_internal_path_is_resolved_from_declaring_object(
    configured: PythonDistributionConfiguration, token: str
) -> None:
    owner = material(configured, "lib/owner.so", needed_elf(f"{token}/internal/path.so"))
    target = material(configured, "lib/internal/path.so", elf())
    dependencies, _ = _elf(owner.read_bytes(), owner=owner, boundary=configured.distribution_root)
    assert dependencies[0].resolved == target
    assert dependencies[0].owner == owner
    manifest = inventory(configured, verify_pins=False)
    assert sum(e.path == "lib/internal/path.so" for e in manifest.entries) == 1


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "x" * 129,
        "$ORIGIN/" + "x" * 1017,
        "/lib/libc.so.6",
        "lib/libc.so.6",
        "./libc.so.6",
        "../libc.so.6",
        "$LIB/libc.so.6",
        "${LIB}/libc.so.6",
        "$PLATFORM/libc.so.6",
        "${PLATFORM}/libc.so.6",
        "$HOME/libc.so.6",
        "$ORIGIN_SUFFIX/libc.so.6",
        "${ORIGIN/libc.so.6",
        "$ORIGIN/lib/$LIB/file.so",
        "$ORIGIN//file.so",
        "$ORIGIN/file.so/",
        "$ORIGIN/lib\\file.so",
        "$ORIGIN/$(command).so",
        "$ORIGIN/`command`.so",
        "$ORIGIN/lib;file.so",
        "$ORIGIN/../../runtime-other/file.so",
        "$ORIGIN/../../../etc/file.so",
        "$ORIGIN/\0file.so",
    ],
)
def test_dependency_syntax_and_escape_fail_closed(name: str) -> None:
    with pytest.raises(ValueError):
        _elf(needed_elf(name), owner=Path("/runtime/lib/libpython3.so"), boundary=Path("/runtime"))


def material(config: PythonDistributionConfiguration, relative: str, content: bytes) -> Path:
    path = config.distribution_root / relative
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    path.write_bytes(content)
    path.chmod(0o644)
    return path


@pytest.mark.parametrize("token", ["$ORIGIN", "${ORIGIN}"])
def test_real_libpython_layout_uses_exact_inventoried_file_once(
    configured: PythonDistributionConfiguration, token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = material(configured, "lib/libpython3.12.so.1.0", elf())
    material(
        configured,
        "lib/libpython3.so",
        needed_elf(
            f"{token}/../lib/libpython3.12.so.1.0",
            f"{token}/../lib/libpython3.12.so.1.0",
            "libpthread.so.0",
            "libc.so.6",
        ),
    )
    for name in ("libpthread.so.0", "libc.so.6"):
        path = configured.system_library_root / name
        path.write_bytes(elf())
        path.chmod(0o644)
    original = distribution._bytes
    reads: list[Path] = []

    def counted(path: Path, maximum: int) -> bytes:
        reads.append(path)
        return original(path, maximum)

    monkeypatch.setattr(distribution, "_bytes", counted)
    manifest = inventory(configured, verify_pins=False)
    assert reads.count(target) == 1
    assert sum(e.path == "lib/libpython3.12.so.1.0" for e in manifest.entries) == 1
    assert {e.path for e in manifest.support_entries} == {
        "ld-linux-x86-64.so.2",
        "libpthread.so.0",
        "libc.so.6",
    }
    assert inventory(configured, verify_pins=False) == manifest
    assert (
        next(e for e in manifest.entries if e.path == "lib/libpython3.so").sha256
        == hashlib.sha256(
            (configured.distribution_root / "lib/libpython3.so").read_bytes()
        ).hexdigest()
    )


@pytest.mark.parametrize("failure", ["missing", "fifo", "mode", "owner", "not_elf", "unmounted"])
def test_dependency_target_must_be_trusted_inventoried_elf(
    configured: PythonDistributionConfiguration, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = configured.distribution_root / "lib/dependency.so"
    raw = "$ORIGIN/dependency.so"
    if failure == "fifo":
        os.mkfifo(target, 0o600)
    elif failure != "missing":
        target = material(
            configured, "lib/dependency.so", b"not ELF" if failure == "not_elf" else elf()
        )
        if failure == "mode":
            target.chmod(0o666)
        elif failure == "owner":
            original = distribution._trust

            def checked(info: os.stat_result, *, link: bool = False) -> None:
                if info.st_ino == target.stat().st_ino:
                    # Simulate an unrelated owner's stat, without requiring chown/root.
                    changed = list(info)
                    changed[4] = 123456
                    original(os.stat_result(changed), link=link)
                else:
                    original(info, link=link)

            monkeypatch.setattr(distribution, "_trust", checked)
        elif failure == "unmounted":
            material(configured, "include/dependency.so", elf())
            raw = "$ORIGIN/../include/dependency.so"
    material(configured, "lib/libpython3.so", needed_elf(raw))
    with pytest.raises(ProvenanceFailure) as error:
        inventory(configured, verify_pins=False)
    assert error.value.failure.runtime_reason is PythonRuntimeReason.RUNTIME_INTEGRITY_FAILURE
    assert str(target) not in str(error.value)


@pytest.mark.parametrize("link_kind", ["one_hop", "chain", "outside", "directory", "file_parent"])
def test_path_dependencies_obey_existing_symlink_and_parent_policy(
    configured: PythonDistributionConfiguration, link_kind: str
) -> None:
    root = configured.distribution_root
    material(configured, "lib/target.so", elf())
    alias = root / "lib/alias.so"
    if link_kind == "one_hop":
        alias.symlink_to("target.so")
    elif link_kind == "chain":
        alias.symlink_to("second.so")
        (root / "lib/second.so").symlink_to("target.so")
    elif link_kind == "outside":
        alias.symlink_to(configured.system_library_root / "ld-linux-x86-64.so.2")
    elif link_kind == "directory":
        alias.symlink_to("python3.12")
    else:
        material(configured, "lib/alias.so", elf())
    raw = "$ORIGIN/alias.so/../target.so" if link_kind == "file_parent" else "$ORIGIN/alias.so"
    material(configured, "lib/libpython3.so", needed_elf(raw))
    if link_kind == "one_hop":
        manifest = inventory(configured, verify_pins=False)
        assert next(e for e in manifest.entries if e.path == "lib/alias.so").target == "target.so"
        assert sum(e.path == "lib/target.so" for e in manifest.entries) == 1
    else:
        with pytest.raises(ProvenanceFailure):
            inventory(configured, verify_pins=False)


def test_same_basename_at_different_paths_binds_exact_targets(
    configured: PythonDistributionConfiguration,
) -> None:
    for branch in ("first", "second"):
        material(configured, f"lib/{branch}/dependency.so", elf())
        material(configured, f"lib/{branch}/owner.so", needed_elf("$ORIGIN/dependency.so"))
    manifest = inventory(configured, verify_pins=False)
    assert {e.path for e in manifest.entries if e.path.endswith("dependency.so")} == {
        "lib/first/dependency.so",
        "lib/second/dependency.so",
    }
    (configured.distribution_root / "lib/second/dependency.so").unlink()
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)


def test_internal_basename_does_not_suppress_external_bare_closure(
    configured: PythonDistributionConfiguration,
) -> None:
    material(configured, "lib/nested/libfixture.so.1", elf())
    material(configured, "lib/owner.so", needed_elf("libfixture.so.1"))
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)
    path = configured.system_library_root / "libfixture.so.1"
    path.write_bytes(elf())
    path.chmod(0o644)
    manifest = inventory(configured, verify_pins=False)
    assert "libfixture.so.1" in {e.path for e in manifest.support_entries}


def test_owner_bound_dependency_records_have_an_aggregate_bound(
    configured: PythonDistributionConfiguration,
) -> None:
    material(configured, "lib/owner.so", needed_elf(*(f"libfixture{i}.so" for i in range(30))))
    bounded = configured.model_copy(update={"max_entries": 16})
    with pytest.raises(ValueError, match="dependency record bound"):
        distribution._inventory(bounded, verify_pins=False)


def test_support_object_path_dependency_is_bound_to_its_own_directory(
    configured: PythonDistributionConfiguration,
) -> None:
    material(configured, "lib/owner.so", needed_elf("libfixture.so.1"))
    support = configured.system_library_root
    (support / "libfixture.so.1").write_bytes(needed_elf("${ORIGIN}/second.so"))
    (support / "second.so").write_bytes(elf())
    for name in ("libfixture.so.1", "second.so"):
        (support / name).chmod(0o644)
    manifest = inventory(configured, verify_pins=False)
    assert {e.path for e in manifest.support_entries} == {
        "ld-linux-x86-64.so.2",
        "libfixture.so.1",
        "second.so",
    }
    (support / "libfixture.so.1").write_bytes(needed_elf("$ORIGIN/nested/second.so"))
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)  # Not mounted at that nested namespace path.
