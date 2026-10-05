"""Static projection fixtures, never candidate execution or real Kali acceptance."""

import hashlib
import json
import stat
import struct
from pathlib import Path

import pytest
from boberagent_contracts import (
    PythonInterpreterIdentity,
    PythonRuntimeProjectionIdentity,
    PythonRuntimeProjectionProfile,
)
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_execution_node.preparation.python_distribution import (
    MANIFEST_ADAPTER,
    DistributionManifest,
    ProvenanceFailure,
    PythonDistributionConfiguration,
    inventory,
    revalidate,
)
from boberagent_execution_node.preparation.python_projection import (
    mount_descriptor,
    projection_mounts,
    verify_exposure,
    write_mount_descriptor,
)
from boberagent_execution_node.preparation.python_provenance import validate_identity
from pydantic import ValidationError
from test_python_provenance import configured as configured
from test_python_provenance import identity_probe, repin


def native_elf(
    *,
    needed: tuple[str, ...] = (),
    soname: str | None = None,
    rpath: str | None = None,
    exports: tuple[str, ...] = (),
    interpreter: bool = False,
) -> bytes:
    """Small ELF64 with real dynamic strings and exported dynamic symbols."""
    data = bytearray(8192)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<HH", data, 16, 3, 62)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HH", data, 54, 56, 3 if interpreter else 2)
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0x1000, 0, len(data), len(data), 4096)
    strings = bytearray(b"\0")

    def string(value: str) -> int:
        offset = len(strings)
        strings.extend(value.encode() + b"\0")
        return offset

    dynamic = [(1, string(value)) for value in needed]
    if soname is not None:
        dynamic.append((14, string(soname)))
    if rpath is not None:
        dynamic.append((15, string(rpath)))
    dynamic.extend(((5, 0x2000), (10, len(strings)), (0, 0)))
    data[0x1000 : 0x1000 + len(strings)] = strings
    for index, pair in enumerate(dynamic):
        struct.pack_into("<qQ", data, 0x200 + index * 16, *pair)
    struct.pack_into(
        "<IIQQQQQQ", data, 120, 2, 4, 0x200, 0x1200, 0, len(dynamic) * 16, len(dynamic) * 16, 8
    )
    if interpreter:
        loader = b"/lib64/ld-linux-x86-64.so.2\0"
        data[0x300 : 0x300 + len(loader)] = loader
        struct.pack_into(
            "<IIQQQQQQ", data, 176, 3, 4, 0x300, 0x1300, 0, len(loader), len(loader), 1
        )
    symbol_strings = bytearray(b"\0")
    for index, value in enumerate(exports):
        offset = len(symbol_strings)
        symbol_strings.extend(value.encode() + b"\0")
        struct.pack_into("<IBBHQQ", data, 0x600 + index * 24, offset, 0x12, 0, 1, 0x1000, 1)
    data[0x680 : 0x680 + len(symbol_strings)] = symbol_strings
    struct.pack_into("<Q", data, 40, 0x800)
    struct.pack_into("<HH", data, 58, 64, 3)
    struct.pack_into(
        "<IIQQQQIIQQ", data, 0x840, 0, 11, 2, 0x1600, 0x600, len(exports) * 24, 2, 0, 8, 24
    )
    struct.pack_into(
        "<IIQQQQIIQQ", data, 0x880, 0, 3, 2, 0x1680, 0x680, len(symbol_strings), 0, 0, 1, 0
    )
    return bytes(data)


def install_feature(config: PythonDistributionConfiguration) -> dict[str, Path]:
    root = config.distribution_root
    native = root / "lib/python3.12/lib-dynload/_tkinter.cpython-312-x86_64-linux-gnu.so"
    tcl, tk = root / "lib/libtcl9.0.so", root / "lib/libtcl9tk9.0.so"
    native.write_bytes(
        native_elf(needed=(tcl.name, tk.name, "libc.so.6"), exports=("PyInit__tkinter",))
    )
    tcl.write_bytes(native_elf(needed=("libc.so.6",), soname=tcl.name, rpath="/tools/deps/lib"))
    tk.write_bytes(
        native_elf(needed=(tcl.name,), soname=tk.name, rpath="/tools/deps/lib:/tools/deps/lib")
    )
    (config.system_library_root / "libc.so.6").write_bytes(native_elf())
    package = root / "lib/python3.12/tkinter"
    package.mkdir(mode=0o755)
    (package / "__init__.py").write_bytes(b"import _tkinter\n")
    (package / "__pycache__").mkdir(mode=0o755)
    (package / "__pycache__/__init__.cpython-312.pyc").write_bytes(b"synthetic cache")
    for name, sentinel in (("tcl9.0", "init.tcl"), ("tk9.0", "tk.tcl")):
        path = root / "lib" / name
        path.mkdir(mode=0o755)
        (path / sentinel).write_bytes(b"# optional feature data\n")
    for path in root.rglob("*"):
        if path.is_file() and path != root / "bin/python3.12":
            path.chmod(0o644)
    return dict(native=native, tcl=tcl, tk=tk, package=package)


def test_complete_base_projects_feature_and_preserves_stdlib(
    configured: PythonDistributionConfiguration,
) -> None:
    paths = install_feature(configured)
    manifest = inventory(repin(configured))
    selected = {e.path for e in manifest.entries}
    excluded = {e.entry.path: e for e in manifest.excluded_entries}
    for name in ("native", "tcl", "tk"):
        path = paths[name].relative_to(configured.distribution_root).as_posix()
        assert path not in selected and path in excluded
    assert excluded["lib/libtcl9.0.so"].role == "EXCLUSIVE_LIBRARY"
    assert excluded["lib/python3.12/tkinter/__init__.py"].role == "PYTHON_PACKAGE"
    assert excluded["lib/tk9.0/tk.tcl"].role == "FEATURE_DATA"
    assert "lib/python3.12/venv/__init__.py" in selected
    assert "lib/python3.12/json.py" in selected
    assert "lib/python3.12/lib-dynload" in selected
    # Native support needed solely by excluded feature is not executable authority.
    assert "libc.so.6" not in {e.path for e in manifest.support_entries}
    assert paths["tcl"].read_bytes().find(b"/tools/deps/lib") > 0
    assert manifest == inventory(repin(configured))
    assert MANIFEST_ADAPTER.validate_json(manifest.model_dump_json()) == manifest
    identity = validate_identity(manifest, identity_probe())
    assert identity.distribution == manifest.identity()
    assert PythonInterpreterIdentity.model_validate_json(identity.model_dump_json()) == identity


def test_exact_exposure_excludes_optional_bytes_and_compressed_mounts(
    configured: PythonDistributionConfiguration,
    tmp_path: Path,
) -> None:
    install_feature(configured)
    manifest = inventory(repin(configured))
    verify_exposure(manifest, manifest.entries)
    with pytest.raises(ValueError, match="exposure mismatch"):
        verify_exposure(manifest, (*manifest.entries, manifest.excluded_entries[0].entry))
    with pytest.raises(ValueError, match="exposure mismatch"):
        verify_exposure(manifest, manifest.entries[:-1])
    mounts = projection_mounts(manifest)
    assert any(m.path == "lib" and m.kind == "DIRECTORY" for m in mounts)
    assert not any(m.path == "lib" and m.kind == "BIND" for m in mounts)
    assert any(m.path == "lib/python3.12/venv" and m.kind == "BIND" for m in mounts)
    descriptor = tmp_path / "projection.mounts"
    write_mount_descriptor(descriptor, manifest)
    assert stat.S_IMODE(descriptor.stat().st_mode) == 0o600
    assert descriptor.read_bytes() == mount_descriptor(manifest)
    assert manifest.projection.projection_sha256.encode() in descriptor.read_bytes()
    assert b"tkinter" not in descriptor.read_bytes() and b"libtcl" not in descriptor.read_bytes()
    with pytest.raises(FileExistsError):
        write_mount_descriptor(descriptor, manifest)


@pytest.mark.parametrize(
    "role",
    ["projected", "shared_consumer", "unknown", "filename_only", "mixed_exports", "malformed"],
)
def test_unknown_or_shared_material_is_never_exempted(
    configured: PythonDistributionConfiguration,
    role: str,
) -> None:
    paths = install_feature(configured)
    root = configured.distribution_root
    if role == "projected":
        (root / "lib/python3.12/lib-dynload/required.so").write_bytes(
            native_elf(rpath="/tools/deps/lib")
        )
    elif role == "shared_consumer":
        (root / "lib/libother.so").write_bytes(native_elf(needed=(paths["tcl"].name,)))
    elif role == "unknown":
        (root / "lib/libunknown.so").write_bytes(
            native_elf(rpath="/tools/deps/lib", soname="libunknown.so")
        )
    elif role == "filename_only":
        paths["native"].write_bytes(native_elf(needed=(paths["tcl"].name,)))
    elif role == "mixed_exports":
        paths["native"].write_bytes(
            native_elf(needed=(paths["tcl"].name,), exports=("PyInit__tkinter", "PyInit_other"))
        )
    else:
        paths["tcl"].write_bytes(b"\x7fELFbroken")
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)


@pytest.mark.parametrize("mutation", ["mode", "bytes", "special", "link"])
def test_excluded_base_material_still_requires_trust_and_exact_hashes(
    configured: PythonDistributionConfiguration,
    mutation: str,
) -> None:
    paths = install_feature(configured)
    config = repin(configured)
    manifest = inventory(config)
    if mutation == "mode":
        paths["tcl"].chmod(0o666)
    elif mutation == "bytes":
        paths["tcl"].write_bytes(native_elf(soname=paths["tcl"].name, rpath="/other/absolute/path"))
        changed = inventory(config, verify_pins=False)
        assert (
            changed.projection.excluded_manifest_sha256
            != manifest.projection.excluded_manifest_sha256
        )
        assert changed.projection.projection_sha256 != manifest.projection.projection_sha256
    elif mutation == "special":
        paths["tcl"].unlink()
        paths["tcl"].mkdir(mode=0o777)
    else:
        paths["tcl"].unlink()
        paths["tcl"].symlink_to("/untrusted")
    with pytest.raises(ProvenanceFailure):
        inventory(config)
    with pytest.raises(ProvenanceFailure):
        revalidate(config, manifest.identity())


def test_origin_interpreter_search_remains_confined(
    configured: PythonDistributionConfiguration,
) -> None:
    (configured.distribution_root / "bin/python3.12").write_bytes(
        native_elf(interpreter=True, rpath="$ORIGIN/../lib")
    )
    manifest = inventory(repin(configured))
    assert "bin/python3.12" in {e.path for e in manifest.entries}


@pytest.mark.parametrize(
    "path",
    [
        "lib/python3.12/tkinter.py",
        "lib/python3.12/_tkinter.pyc",
        "lib/python3.12/ensurepip.py",
        "lib/python312.zip",
    ],
)
def test_no_alternative_gui_import_or_third_party_fallback(
    configured: PythonDistributionConfiguration,
    path: str,
) -> None:
    install_feature(configured)
    file = configured.distribution_root / path
    file.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    file.write_bytes(b"# unapproved alternative\n")
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)


def test_excluded_dependency_records_still_obey_inventory_bounds(
    configured: PythonDistributionConfiguration,
) -> None:
    paths = install_feature(configured)
    paths["tcl"].write_bytes(
        native_elf(
            needed=tuple(f"lib{i}.so" for i in range(50)),
            soname=paths["tcl"].name,
            rpath="/tools/deps/lib",
        )
    )
    from boberagent_execution_node.preparation.python_distribution import _inspect_elf

    assert (
        len(
            _inspect_elf(
                paths["tcl"].read_bytes(), owner=paths["tcl"], boundary=configured.distribution_root
            ).needed
        )
        == 50
    )
    with pytest.raises(ProvenanceFailure):
        inventory(configured.model_copy(update={"max_entries": 40}), verify_pins=False)


def test_unknown_namespace_package_cannot_reintroduce_gui_feature(
    configured: PythonDistributionConfiguration,
) -> None:
    paths = install_feature(configured)
    (paths["package"] / "__init__.py").unlink()
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)


def test_profile_and_manifest_versions_are_bound_and_historical_v1_unchanged(
    configured: PythonDistributionConfiguration,
) -> None:
    projected = inventory(configured)
    historical = DistributionManifest(
        root_binding_sha256=projected.root_binding_sha256,
        interpreter_sha256=projected.interpreter_sha256,
        entries=projected.entries,
        support_entries=projected.support_entries,
        metadata_sha256=projected.metadata_sha256,
    )
    wire = historical.model_dump(mode="json")
    # Exact old schema, with no defaults/projection introduced on old objects.
    old_json = json.dumps(wire, sort_keys=True, separators=(",", ":"))
    assert historical.digest == hashlib.sha256(old_json.encode()).hexdigest()
    assert MANIFEST_ADAPTER.validate_json(old_json) == historical
    pins = historical.identity().model_dump(mode="json")
    assert "projection" not in pins and pins["manifest_version"].endswith("@1")
    assert (
        canonical_digest(historical.identity())
        == hashlib.sha256(
            json.dumps(pins, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert historical.digest != projected.digest
    with pytest.raises(ProvenanceFailure):
        revalidate(configured, historical.identity())
    profile = projected.projection.profile.model_dump(mode="json")
    profile_changes: tuple[dict[str, object], ...] = (
        {"profile_version": "2"},
        {"unsupported_optional": []},
        {"required": ["INTERPRETER"]},
    )
    for changes in profile_changes:
        with pytest.raises(ValidationError):
            PythonRuntimeProjectionProfile.model_validate({**profile, **changes})
    projection = projected.projection.model_dump(mode="json")
    with pytest.raises(ValidationError):
        PythonRuntimeProjectionIdentity.model_validate({**projection, "profile_sha256": "f" * 64})
    with pytest.raises(ValidationError):
        PythonRuntimeProjectionIdentity.model_validate(
            {**projection, "projection_sha256": "f" * 64}
        )
