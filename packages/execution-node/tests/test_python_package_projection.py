"""Package-manager projection is static evidence, never install/runtime acceptance."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from boberagent_contracts import PythonRuntimeProjectionProfile
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_execution_node.preparation import python_distribution as distribution
from boberagent_execution_node.preparation.python_distribution import (
    MANIFEST_ADAPTER,
    ProjectedDistributionManifest,
    ProvenanceFailure,
    PythonDistributionConfiguration,
    inventory,
    revalidate,
)
from boberagent_execution_node.preparation.python_projection import (
    mount_descriptor,
    verify_exposure,
)
from test_python_projection import install_feature, native_elf
from test_python_provenance import configured as configured
from test_python_provenance import repin


def add_file(root: Path, relative: str, data: bytes, *, executable: bool = False) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    path.write_bytes(data)
    path.chmod(0o755 if executable else 0o644)
    return path


def provision(config: PythonDistributionConfiguration, version: str = "26.2.1") -> Path:
    """Representative uv/distlib layout, no package imported and no interpreter run."""
    root = config.distribution_root
    site = "lib/python3.12/site-packages/"
    add_file(root, site + "README.txt", b"operator provisioned base\n")
    add_file(root, site + "pip/__init__.py", b"# synthetic package\n")
    add_file(root, site + "pip/_internal/cli/main.py", b"def main(): return 0\n")
    add_file(
        root,
        site + f"pip-{version}.dist-info/METADATA",
        f"Name: pip\nVersion: {version}\n".encode(),
    )
    add_file(
        root,
        site + f"pip-{version}.dist-info/entry_points.txt",
        b"[console_scripts]\npip = pip._internal.cli.main:main\n",
    )
    add_file(root, site + "other_package/__init__.py", b"# unrelated third party\n")
    add_file(root, site + "other_package/__pycache__/module.pyc", b"synthetic cache")
    for name in ("pip", "pip3", "pip3.12", "renamed-package-tool"):
        add_file(
            root,
            "bin/" + name,
            b"#!/operator/base/bin/python3.12\nimport sys\n"
            b"from pip._internal.cli.main import main\n"
            b"if __name__ == '__main__':\n    sys.exit(main())\n",
            executable=True,
        )
    (root / "bin/provisioning-alias").symlink_to("renamed-package-tool")
    add_file(root, "lib/python3.12/ensurepip/__init__.py", b"# bootstrap\n")
    add_file(root, "lib/python3.12/ensurepip/__main__.py", b"from . import bootstrap\n")
    add_file(
        root, "lib/python3.12/ensurepip/_bundled/pip-next-py3-none-any.whl", b"synthetic wheel"
    )
    add_file(root, "lib/python3.12/ensurepip/__pycache__/__init__.pyc", b"synthetic cache")
    return root


@pytest.mark.parametrize("version", ["26.2.1", "99.123.7"])
def test_complete_package_manager_feature_is_excluded_and_hash_bound(
    configured: PythonDistributionConfiguration,
    version: str,
) -> None:
    root = provision(configured, version)
    install_feature(configured)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    manifest = inventory(repin(configured))
    selected = {e.path for e in manifest.entries}
    excluded = {e.entry.path: e for e in manifest.excluded_entries}
    package_entries = {
        e.entry.path for e in manifest.excluded_entries if e.feature == "PACKAGE_MANAGER"
    }
    assert manifest.projection.profile.profile_version == "1"
    assert manifest.projection.profile.unsupported_optional == ("TKINTER_TCL_TK", "PACKAGE_MANAGER")
    assert not any(distribution._package_manager_path(p) for p in selected)
    assert "lib/python3.12/site-packages" in package_entries
    assert f"lib/python3.12/site-packages/pip-{version}.dist-info/METADATA" in package_entries
    assert "lib/python3.12/site-packages/README.txt" in package_entries
    assert "lib/python3.12/site-packages/other_package/__pycache__/module.pyc" in package_entries
    assert "lib/python3.12/ensurepip/_bundled/pip-next-py3-none-any.whl" in package_entries
    assert "lib/python3.12/ensurepip" in package_entries
    assert "lib/python3.12/venv/__init__.py" in selected
    for name in ("pip", "pip3", "pip3.12", "renamed-package-tool", "provisioning-alias"):
        assert excluded["bin/" + name].role == "LAUNCHER"
        assert excluded["bin/" + name].feature == "PACKAGE_MANAGER"
    for e in manifest.excluded_entries:
        if e.entry.kind == "file":
            assert e.entry.sha256 == hashlib.sha256((root / e.entry.path).read_bytes()).hexdigest()
    descriptor = mount_descriptor(manifest)
    assert not any(
        name in descriptor for name in (b"site-packages", b"ensurepip", b"bin/pip", b"tkinter")
    )
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert MANIFEST_ADAPTER.validate_json(manifest.model_dump_json()) == manifest


@pytest.mark.parametrize("namespace", ["site-packages", "ensurepip"])
def test_empty_namespace_is_also_excluded(
    configured: PythonDistributionConfiguration,
    namespace: str,
) -> None:
    (configured.distribution_root / "lib/python3.12" / namespace).mkdir(mode=0o755)
    manifest = inventory(repin(configured))
    assert len(manifest.excluded_entries) == 1
    assert manifest.excluded_entries[0].entry.path.endswith("/" + namespace)
    assert not any(e.path.endswith("/" + namespace) for e in manifest.entries)


@pytest.mark.parametrize(
    "relative",
    [
        "lib/python3.12/site-packages/README.txt",
        "lib/python3.12/site-packages/pip-26.2.1.dist-info/METADATA",
        "lib/python3.12/ensurepip/_bundled/pip-next-py3-none-any.whl",
        "bin/pip",
    ],
)
def test_excluded_bytes_mutation_changes_projection_and_invalidates_pins(
    configured: PythonDistributionConfiguration,
    relative: str,
) -> None:
    root = provision(configured)
    config = repin(configured)
    manifest = inventory(config)
    path = root / relative
    path.write_bytes(path.read_bytes() + b"\n# drift\n")
    changed = inventory(config, verify_pins=False)
    assert changed.projection.base_manifest_sha256 != manifest.projection.base_manifest_sha256
    assert (
        changed.projection.excluded_manifest_sha256 != manifest.projection.excluded_manifest_sha256
    )
    assert changed.projection.projection_sha256 != manifest.projection.projection_sha256
    with pytest.raises(ProvenanceFailure):
        revalidate(config, manifest.identity())


@pytest.mark.parametrize("mutation", ["mode", "parent", "owner", "fifo", "link", "oversized"])
def test_excluded_material_still_fails_base_integrity(
    configured: PythonDistributionConfiguration,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    root = provision(configured)
    path = root / "lib/python3.12/site-packages/README.txt"
    if mutation == "mode":
        path.chmod(0o666)
    elif mutation == "parent":
        path.parent.chmod(0o777)
    elif mutation == "owner":
        original = distribution._trust

        def foreign_owner(info: os.stat_result, *, link: bool = False) -> None:
            if info.st_ino == path.stat().st_ino:
                fields = list(info)
                fields[4] = os.getuid() + 12345
                info = os.stat_result(fields)
            original(info, link=link)

        monkeypatch.setattr(distribution, "_trust", foreign_owner)
    elif mutation == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif mutation == "link":
        path.unlink()
        path.symlink_to("/untrusted")
    else:
        configured = configured.model_copy(update={"max_runtime_bytes": 100})
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)


def test_excluded_native_eligibility_grants_no_execution_authority(
    configured: PythonDistributionConfiguration,
) -> None:
    root = provision(configured)
    install_feature(configured)
    # Unavailable external dependency and absolute RPATH are structural evidence,
    # not support roots or executable eligibility for this excluded native object.
    native = add_file(
        root,
        "lib/python3.12/site-packages/other_package/native.so",
        native_elf(needed=("missing.so", "libtcl9.0.so"), rpath="/tools/deps/lib"),
    )
    manifest = inventory(repin(configured))
    assert native.relative_to(root).as_posix() in {e.entry.path for e in manifest.excluded_entries}
    assert "missing.so" not in {e.path for e in manifest.support_entries}
    assert b"native.so" not in mount_descriptor(manifest)
    native.write_bytes(b"\x7fELFbroken")
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)


def test_retained_native_cannot_depend_on_excluded_native(
    configured: PythonDistributionConfiguration,
) -> None:
    root = provision(configured)
    add_file(root, "lib/python3.12/site-packages/native.so", native_elf())
    add_file(
        root,
        "lib/python3.12/lib-dynload/required.so",
        native_elf(needed=("$ORIGIN/../site-packages/native.so",)),
    )
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)


@pytest.mark.parametrize(
    "code",
    [
        b"import pip\n",
        b"import runpy\nrunpy.run_module('pip', run_name='__main__')\n",
        b"import ensurepip\nensurepip.bootstrap()\n",
        b"import importlib\nimportlib.import_module(target)\n",
        b"from runpy import run_module as go\ngo('pip', run_name='__main__')\n",
        b"from pkg_resources import load_entry_point\nload_entry_point('pip==26', 'console_scripts', 'pip')()\n",
        b"this is not valid python!\n",
    ],
)
def test_uncertified_launcher_into_excluded_material_rejects(
    configured: PythonDistributionConfiguration,
    code: bytes,
) -> None:
    root = provision(configured)
    add_file(root, "bin/innocent-name", b"#!/operator/python3.12\n" + code, executable=True)
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)


@pytest.mark.parametrize("target", ["../lib/python3.12/site-packages/README.txt", "pip"])
def test_arbitrary_retained_link_cannot_reach_package_manager(
    configured: PythonDistributionConfiguration,
    target: str,
) -> None:
    root = provision(configured)
    # bin aliases of proven launchers are intentionally excluded; other aliases
    # into excluded data or a different retained import location must fail.
    path = root / ("bin/data-alias" if target.startswith("../") else "lib/exposed")
    path.symlink_to(target if path.parent.name == "bin" else "../bin/" + target)
    with pytest.raises(ProvenanceFailure):
        inventory(configured, verify_pins=False)


def test_normal_stdlib_tools_remain_but_structural_gui_launcher_is_excluded(
    configured: PythonDistributionConfiguration,
) -> None:
    root = provision(configured)
    install_feature(configured)
    add_file(root, "lib/python3.12/idlelib/pyshell.py", b"from tkinter import *\n")
    add_file(root, "lib/python3.12/pydoc.py", b"def safeimport(path): return __import__(path)\n")
    add_file(root, "lib/python3.12/lib2to3/main.py", b"# normal stdlib\n")
    add_file(
        root,
        "bin/not-named-idle",
        b"#!/operator/python3.12\n"
        b"from idlelib.pyshell import main\nif __name__ == '__main__':\n    main()\n",
        executable=True,
    )
    (root / "bin/idle3.12").symlink_to("not-named-idle")
    add_file(
        root,
        "bin/pydoc3.12",
        b"#!/operator/python3.12\nimport pydoc\nif __name__ == '__main__':\n    pydoc.cli()\n",
        executable=True,
    )
    add_file(
        root,
        "bin/2to3-3.12",
        b"#!/operator/python3.12\nimport sys\n"
        b"from lib2to3.main import main\nsys.exit(main('lib2to3.fixes'))\n",
        executable=True,
    )
    add_file(root, "bin/python3.12-config", b"#!/bin/sh\necho configuration\n", executable=True)
    # Names alone never establish package-manager behavior.
    add_file(root, "bin/pip-unrelated", b"#!/bin/sh\necho harmless\n", executable=True)
    manifest = inventory(repin(configured))
    selected = {e.path for e in manifest.entries}
    excluded = {e.entry.path: e for e in manifest.excluded_entries}
    for name in ("pydoc3.12", "2to3-3.12", "python3.12-config", "pip-unrelated", "python3.12"):
        assert "bin/" + name in selected
    for name in ("not-named-idle", "idle3.12"):
        assert excluded["bin/" + name].feature == "TKINTER_TCL_TK"
        assert excluded["bin/" + name].role == "LAUNCHER"
    assert "lib/python3.12/idlelib/pyshell.py" in selected  # no speculative stdlib deletion


def test_future_exposure_rejects_every_excluded_feature(
    configured: PythonDistributionConfiguration,
) -> None:
    provision(configured)
    install_feature(configured)
    manifest = inventory(repin(configured))
    verify_exposure(manifest, manifest.entries)
    for entry in manifest.excluded_entries:
        with pytest.raises(ValueError, match="exposure mismatch"):
            verify_exposure(manifest, (*manifest.entries, entry.entry))


def test_historical_tk_only_v2_evidence_is_not_reinterpreted(
    configured: PythonDistributionConfiguration,
) -> None:
    manifest = inventory(configured)
    historical = manifest.model_dump(mode="json")
    profile = PythonRuntimeProjectionProfile(unsupported_optional=("TKINTER_TCL_TK",))
    projection = historical["projection"]
    projection["profile"] = profile.model_dump(mode="json")
    projection["profile_sha256"] = canonical_digest(profile)
    projection.pop("projection_sha256")
    projection["projection_sha256"] = distribution.digest_value(projection)
    wire = json.dumps(historical, sort_keys=True, separators=(",", ":"))
    retained = MANIFEST_ADAPTER.validate_json(wire)
    assert isinstance(retained, ProjectedDistributionManifest)
    assert retained.digest == hashlib.sha256(wire.encode()).hexdigest()
    assert retained.model_dump(mode="json") == historical
    assert retained.digest != manifest.digest
    with pytest.raises(ProvenanceFailure):
        revalidate(configured, retained.identity())
    with pytest.raises(ValueError, match="historical projection"):
        verify_exposure(retained, retained.entries)
    with pytest.raises(ValueError, match="historical projection"):
        mount_descriptor(retained)
