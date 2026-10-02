"""Trusted E4 host preflight; real bubblewrap is optional in portable CI."""

import shutil
import sys
from pathlib import Path

import pytest
from boberagent_contracts.runtime_preparation import ConfinementFeature
from boberagent_execution_node.preparation.confinement import (
    BubblewrapConfinementBackend,
    ConfinementUnavailable,
)


def test_absent_backend_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(ConfinementUnavailable, match="CONFINEMENT_UNAVAILABLE"):
        BubblewrapConfinementBackend().preflight()


def test_binary_presence_without_namespace_probe_does_not_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "bwrap"
    fake.write_text(
        "#!/bin/sh\nif [ \"$1\" = --version ]; then echo 'bubblewrap 0.11.0'; else exit 1; fi\n"
    )
    fake.chmod(0o700)
    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name: str(fake) if name == "bwrap" else real_which(name)
    )
    with pytest.raises(ConfinementUnavailable, match="CONFINEMENT_PROBE_FAILED"):
        BubblewrapConfinementBackend().preflight()


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
