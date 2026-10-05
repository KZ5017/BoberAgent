"""Offline native ownership proofs, not real Kali provenance acceptance."""

import hashlib
import os
import stat

import pytest
from boberagent_execution_node.preparation import python_distribution as distribution
from boberagent_execution_node.preparation.python_distribution import (
    ManifestEntry,
    ProvenanceFailure,
    PythonDistributionConfiguration,
    inventory,
)
from boberagent_execution_node.preparation.python_projection import (
    mount_descriptor,
    verify_exposure,
)
from test_python_projection import install_feature, native_elf
from test_python_provenance import configured as configured


def graph(config: PythonDistributionConfiguration) -> distribution._NativeProjectionGraph:
    """Inspect the same structural graph; public inventory still enforces trust."""
    root = config.distribution_root
    entries = []
    metadata = {}
    links = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        fields: distribution.EntryFields = dict(
            path=relative, mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid
        )
        if path.is_symlink():
            entries.append(ManifestEntry(kind="symlink", target=os.readlink(path), **fields))
            links[path] = path.resolve()
        elif path.is_dir():
            entries.append(ManifestEntry(kind="directory", **fields))
        else:
            content = path.read_bytes()
            entries.append(
                ManifestEntry(
                    kind="file",
                    size=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                    **fields,
                )
            )
            metadata[path] = distribution._inspect_elf(content, owner=path, boundary=root)
    tkinter = {p for p, facts in metadata.items() if facts.python_exports == ("PyInit__tkinter",)}
    return distribution._dependency_ownership(root, tuple(entries), metadata, links, tkinter)


def assert_bounded_failure(config: PythonDistributionConfiguration) -> None:
    with pytest.raises(ProvenanceFailure) as caught:
        inventory(config, verify_pins=False)
    assert caught.value.failure.runtime_reason is not None
    assert caught.value.failure.runtime_reason.value == "RUNTIME_INTEGRITY_FAILURE"
    assert caught.value.stage == "distribution_inventory"
    assert str(config.distribution_root) not in str(caught.value)
    assert "/tools/deps/lib" not in str(caught.value)


@pytest.mark.parametrize("declared_soname", [True, False])
def test_reported_graph_is_unsupported_only_and_exactly_partitioned(
    configured: PythonDistributionConfiguration, declared_soname: bool
) -> None:
    paths = install_feature(configured)
    root = configured.distribution_root
    paths["native"].write_bytes(
        native_elf(
            needed=(
                "libtcl9tk9.0.so",
                "libpthread.so.0",
                "libtcl9.0.so",
                "libdl.so.2",
                "libm.so.6",
                "libc.so.6",
            ),
            exports=("PyInit__tkinter",),
        )
    )
    if not declared_soname:
        # Compatibility reproducer: Kali's SONAME tags were not supplied.
        for key, rpath in (("tcl", "/tools/deps/lib"), ("tk", "/tools/deps/lib:/tools/deps/lib")):
            paths[key].write_bytes(native_elf(rpath=rpath))
    facts = graph(configured)
    assert facts.edges[paths["native"]] == {paths["tcl"], paths["tk"]}
    for key in ("native", "tcl", "tk"):
        assert facts.ownership[paths[key]] is distribution._DependencyOwnership.UNSUPPORTED_ONLY
    manifest = inventory(configured, verify_pins=False)
    selected = {root / e.path for e in manifest.entries}
    excluded = {root / e.entry.path for e in manifest.excluded_entries}
    base = {p for tree in ("bin", "lib") for p in (root / tree, *(root / tree).rglob("*"))}
    assert not selected & excluded
    assert selected | excluded == base
    assert not {paths["native"], paths["tcl"], paths["tk"]} & selected
    assert {paths["native"], paths["tcl"], paths["tk"]} <= excluded
    assert root / "lib/tcl9.0/init.tcl" in excluded
    assert root / "lib/tk9.0/tk.tcl" in excluded
    assert root / "lib/python3.12/venv/__init__.py" in selected
    assert (
        facts.ownership[root / "bin/python3.12"] is distribution._DependencyOwnership.SUPPORTED_ONLY
    )
    for key in ("tcl", "tk"):
        entry = next(
            e.entry for e in manifest.excluded_entries if root / e.entry.path == paths[key]
        )
        assert entry.sha256 == hashlib.sha256(paths[key].read_bytes()).hexdigest()
    assert b"libtcl" not in mount_descriptor(manifest)
    assert manifest == inventory(configured, verify_pins=False)


@pytest.mark.parametrize("second_root", ["tkinter", "package_manager"])
def test_multiple_unsupported_roots_are_not_supported_consumers(
    configured: PythonDistributionConfiguration, second_root: str
) -> None:
    paths = install_feature(configured)
    root = configured.distribution_root
    if second_root == "tkinter":
        owner = root / "lib/python3.12/lib-dynload/_tkinter.abi3.so"
        exports = ("PyInit__tkinter",)
    else:
        owner = root / "lib/python3.12/site-packages/provisioning.so"
        owner.parent.mkdir(mode=0o755)
        exports = ("PyInit_provisioning",)
    owner.write_bytes(native_elf(needed=(paths["tcl"].name,), exports=exports))
    facts = graph(configured)
    assert facts.ownership[paths["tcl"]] is distribution._DependencyOwnership.UNSUPPORTED_ONLY
    manifest = inventory(configured, verify_pins=False)
    assert paths["tcl"].relative_to(root).as_posix() not in {e.path for e in manifest.entries}
    assert owner.relative_to(root).as_posix() not in {e.path for e in manifest.entries}
    assert manifest == inventory(configured, verify_pins=False)


@pytest.mark.parametrize("cycle", [False, True])
def test_transitive_feature_libraries_do_not_become_supported_roots(
    configured: PythonDistributionConfiguration, cycle: bool
) -> None:
    paths = install_feature(configured)
    root = configured.distribution_root
    helper = root / "lib/libfeature-helper.so"
    helper.write_bytes(
        native_elf(
            needed=(paths["tcl"].name,) if cycle else (),
            soname=helper.name,
            rpath="/tools/deps/lib",
        )
    )
    # No SONAME on reached Tcl: absence must not promote it to a supported root.
    paths["tcl"].write_bytes(native_elf(needed=(helper.name,), rpath="/tools/deps/lib"))
    facts = graph(configured)
    assert facts.edges[paths["tcl"]] == {helper}
    assert facts.ownership[helper] is distribution._DependencyOwnership.UNSUPPORTED_ONLY
    manifest = inventory(configured, verify_pins=False)
    assert "lib/libfeature-helper.so" not in {e.path for e in manifest.entries}
    assert (
        next(
            e for e in manifest.excluded_entries if e.entry.path == "lib/libfeature-helper.so"
        ).role
        == "EXCLUSIVE_LIBRARY"
    )


@pytest.mark.parametrize("rpath", ["$ORIGIN", "/tools/deps/lib"])
def test_genuine_supported_extension_makes_library_shared_not_exempt(
    configured: PythonDistributionConfiguration, rpath: str
) -> None:
    paths = install_feature(configured)
    root = configured.distribution_root
    consumer = root / "lib/python3.12/lib-dynload/consumer.cpython-312-x86_64-linux-gnu.so"
    consumer.write_bytes(native_elf(needed=(paths["tcl"].name,), exports=("PyInit_consumer",)))
    paths["tcl"].write_bytes(native_elf(soname=paths["tcl"].name, rpath=rpath))
    facts = graph(configured)
    assert facts.ownership[consumer] is distribution._DependencyOwnership.SUPPORTED_ONLY
    assert facts.ownership[paths["tcl"]] is distribution._DependencyOwnership.SHARED
    assert facts.ownership[paths["tk"]] is distribution._DependencyOwnership.UNSUPPORTED_ONLY
    if rpath.startswith("/"):
        assert_bounded_failure(configured)
    else:
        manifest = inventory(configured, verify_pins=False)
        selected = {e.path for e in manifest.entries}
        assert "lib/libtcl9.0.so" in selected and "lib/libtcl9tk9.0.so" not in selected
        assert "lib/tcl9.0/init.tcl" in selected and "lib/tk9.0/tk.tcl" not in selected
        # Exact internal binding does not require a second external Tcl copy.
        assert "libtcl9.0.so" not in {e.path for e in manifest.support_entries}


@pytest.mark.parametrize("unknown", ["orphan", "cycle", "soname_conflict"])
def test_unknown_or_ambiguous_library_ownership_fails_closed(
    configured: PythonDistributionConfiguration, unknown: str
) -> None:
    paths = install_feature(configured)
    root = configured.distribution_root
    if unknown == "soname_conflict":
        paths["tcl"].write_bytes(native_elf(soname="different-identity.so", rpath="$ORIGIN"))
        with pytest.raises(ValueError, match="SONAME conflict"):
            graph(configured)
    else:
        a, b = root / "lib/liborphan.so", root / "lib/libcycle.so"
        a.write_bytes(native_elf(soname=a.name, needed=(b.name,) if unknown == "cycle" else ()))
        if unknown == "cycle":
            b.write_bytes(native_elf(soname=b.name, needed=(a.name,)))
        assert graph(configured).ownership[a] is distribution._DependencyOwnership.UNKNOWN
    assert_bounded_failure(configured)


@pytest.mark.parametrize("alias_path", ["lib/other-name.so", "bin/alternate-native"])
def test_symlink_alias_is_excluded_and_cannot_be_reexposed(
    configured: PythonDistributionConfiguration, alias_path: str
) -> None:
    paths = install_feature(configured)
    root = configured.distribution_root
    alias = root / alias_path
    alias.symlink_to(os.path.relpath(paths["tcl"], alias.parent))
    manifest = inventory(configured, verify_pins=False)
    assert alias_path not in {e.path for e in manifest.entries}
    entry = next(e.entry for e in manifest.excluded_entries if e.entry.path == alias_path)
    assert entry.kind == "symlink"
    with pytest.raises(ValueError, match="exposure mismatch"):
        verify_exposure(manifest, (*manifest.entries, entry))
    assert alias_path.encode() not in mount_descriptor(manifest)


@pytest.mark.parametrize("kind", ["copy", "hardlink"])
def test_alternate_native_bytes_cannot_reintroduce_excluded_library(
    configured: PythonDistributionConfiguration, kind: str
) -> None:
    paths = install_feature(configured)
    paths["tcl"].write_bytes(native_elf(rpath="$ORIGIN"))
    alias = configured.distribution_root / "lib/alternate-native.so"
    if kind == "hardlink":
        os.link(paths["tcl"], alias)
    else:
        alias.write_bytes(paths["tcl"].read_bytes())
    assert_bounded_failure(configured)


def test_native_needed_alias_binds_canonical_inventoried_target(
    configured: PythonDistributionConfiguration,
) -> None:
    paths = install_feature(configured)
    root = configured.distribution_root
    target = root / "lib/tcl-private-image"
    paths["tcl"].rename(target)
    paths["tcl"].symlink_to(target.name)
    facts = graph(configured)
    assert target in facts.edges[paths["native"]]
    assert facts.ownership[target] is distribution._DependencyOwnership.UNSUPPORTED_ONLY
    manifest = inventory(configured, verify_pins=False)
    assert {"lib/libtcl9.0.so", "lib/tcl-private-image"}.isdisjoint(
        e.path for e in manifest.entries
    )


def test_supported_core_api_library_and_abi_forwarder_are_explicit_roots(
    configured: PythonDistributionConfiguration,
) -> None:
    paths = install_feature(configured)
    root = configured.distribution_root
    core = root / "lib/libpython3.12.so.1.0"
    core.write_bytes(native_elf(soname=core.name, exports=("Py_Initialize", "Py_GetVersion")))
    forwarder = root / "lib/libpython3.so"
    forwarder.write_bytes(native_elf(soname=forwarder.name, needed=(core.name,)))
    facts = graph(configured)
    assert facts.ownership[core] is distribution._DependencyOwnership.SUPPORTED_ONLY
    assert facts.ownership[forwarder] is distribution._DependencyOwnership.SUPPORTED_ONLY
    assert facts.ownership[paths["tcl"]] is distribution._DependencyOwnership.UNSUPPORTED_ONLY
    manifest = inventory(configured, verify_pins=False)
    assert {"lib/libpython3.so", "lib/libpython3.12.so.1.0"} <= {e.path for e in manifest.entries}


def test_supported_consumer_cannot_retain_unsupported_tkinter_entry_point(
    configured: PythonDistributionConfiguration,
) -> None:
    paths = install_feature(configured)
    consumer = configured.distribution_root / "lib/python3.12/lib-dynload/consumer.so"
    consumer.write_bytes(
        native_elf(needed=("$ORIGIN/" + paths["native"].name,), exports=("PyInit_consumer",))
    )
    assert_bounded_failure(configured)
