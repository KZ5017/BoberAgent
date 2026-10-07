"""Installed E5-E asset trust, not real Kali confinement/construction proof."""

import asyncio
import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from boberagent_contracts import DomainRef, PreparationReasonCode
from boberagent_execution_node.config import ToolConfiguration
from boberagent_execution_node.identity import NodeId
from boberagent_execution_node.persistence import RuntimeDatabase
from boberagent_execution_node.persistence.migrations import upgrade_database
from boberagent_execution_node.persistence.orm import RuntimeConfinementRow
from boberagent_execution_node.preparation import runtime_confinement as runtime
from boberagent_execution_node.preparation.python_distribution import (
    ProvenanceFailure,
    PythonDistributionConfiguration,
    _parents,
)
from boberagent_execution_node.preparation.runtime_confinement import (
    LinuxRuntimeConfinementBackend,
    RuntimeConfinementUnavailable,
    _trusted_tool,
)
from boberagent_execution_node.preparation.runtime_confinement_models import (
    ConfinementFailureStage,
    EnvironmentLimits,
    ProbeEvidence,
    RuntimeConfinementConfiguration,
    TrustedPythonOperation,
)
from boberagent_execution_node.tools import ToolRegistry
from test_python_provenance import configured as configured
from test_python_provenance import elf, identity_probe


class AssetCase:
    def __init__(
        self,
        backend: LinuxRuntimeConfinementBackend,
        database: RuntimeDatabase,
        source: Path,
        installed: Path,
        digest: str,
    ) -> None:
        self.backend, self.database = backend, database
        self.source, self.installed, self.digest = source, installed, digest


@pytest.fixture
def asset(
    configured: PythonDistributionConfiguration,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[AssetCase]:
    # Reuse D's portable parent-chain fixture: only /tmp outside this test root
    # is omitted. Within the fixture all real trust checks run unchanged.
    del configured
    bundled = Path(runtime.__file__).with_name("_environment_helper.py").read_bytes()
    checkout = tmp_path / "checkout" / "preparation"
    checkout.mkdir(parents=True)
    checkout.parent.chmod(0o775)
    checkout.chmod(0o775)
    source = checkout / "_environment_helper.py"
    source.write_bytes(bundled)
    source.chmod(0o664)
    monkeypatch.setattr(runtime, "__file__", str(checkout / "runtime_confinement.py"))
    trusted = tmp_path / "trusted-tools"
    trusted.mkdir(mode=0o755)
    helper = trusted / "native-helper"
    helper.write_bytes(elf())  # static ELF structure only; never executed
    helper.chmod(0o755)
    digest = hashlib.sha256(bundled).hexdigest()
    installed = trusted / f"environment-{digest}.py"
    installed.write_bytes(bundled)
    installed.chmod(0o444)
    configuration = RuntimeConfinementConfiguration(
        delegated_parent=tmp_path / "delegation",
        helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),
        bubblewrap_sha256="2" * 64,
    )
    tools = ToolRegistry()
    tools.register(configuration.helper_tool, ToolConfiguration(executable=str(helper)))
    asyncio.run(tools.refresh())
    database = RuntimeDatabase(tmp_path / "asset.sqlite3")
    upgrade_database(database)
    backend = LinuxRuntimeConfinementBackend(
        configuration=configuration,
        node_id=NodeId("node-asset"),
        tools=tools,
        database=database,
        runtime_directory=tmp_path / "runtime",
        boot_generation=DomainRef("boot-asset"),
    )
    yield AssetCase(backend, database, source, installed, digest)
    database.close()


def test_checkout_is_data_only_installed_asset_is_the_execution_path(asset: AssetCase) -> None:
    before = (asset.source.stat(), asset.source.parent.stat())
    with pytest.raises(ProvenanceFailure):
        _parents(asset.source.parent)
    assert asset.backend._environment_helper(asset.digest) == asset.installed
    assert (asset.source.stat(), asset.source.parent.stat()) == before
    assert asset.source.stat().st_mode & 0o777 == 0o664
    assert asset.source.parent.stat().st_mode & 0o777 == 0o775


@pytest.mark.parametrize(
    "drift", ["bytes", "mode", "symlink", "parent", "parent_symlink", "missing", "wrong_sha"]
)
@pytest.mark.parametrize("operation", ["create", "verify"])
def test_asset_drift_denies_before_environment_execution_or_journal(
    asset: AssetCase,
    configured: PythonDistributionConfiguration,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
    operation: str,
) -> None:
    expected = asset.digest
    if drift == "bytes":
        asset.installed.chmod(0o644)
        asset.installed.write_bytes(b"raise RuntimeError('never executed')\n")
        asset.installed.chmod(0o444)
    elif drift == "mode":
        asset.installed.chmod(0o664)
    elif drift == "symlink":
        asset.installed.unlink()
        asset.installed.symlink_to(asset.source)
    elif drift == "parent":
        asset.installed.parent.chmod(0o775)
    elif drift == "parent_symlink":
        directory = asset.installed.parent
        moved = directory.with_name("moved-tools")
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    elif drift == "missing":
        asset.installed.unlink()
    else:
        expected = "0" * 64

    async def forbidden(*args: object, **kwargs: object) -> ProbeEvidence:
        pytest.fail("untrusted asset reached environment execution")

    monkeypatch.setattr(asset.backend, "_run_operation", forbidden)

    async def run() -> None:
        with pytest.raises(RuntimeConfinementUnavailable) as error:
            if operation == "create":
                await asset.backend.run_environment_create(
                    configured, DomainRef("build-asset"), tmp_path / "export", expected
                )
            else:
                await asset.backend.run_environment_verify(
                    configured, DomainRef("verify-asset"), tmp_path / "venv", expected
                )
        assert error.value.failure.reason_code is PreparationReasonCode.CONFINEMENT_UNAVAILABLE
        assert str(asset.installed) not in str(error.value)
        assert not (tmp_path / "export").exists()
        with asset.database.transaction() as session:
            assert session.get(RuntimeConfinementRow, "build-asset") is None
            assert session.get(RuntimeConfinementRow, "verify-asset") is None

    asyncio.run(run())


def test_both_operations_bind_the_same_installed_hash_and_recheck_afterward(
    asset: AssetCase,
    configured: PythonDistributionConfiguration,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[TrustedPythonOperation] = []

    async def closed(
        operation: TrustedPythonOperation,
        operation_id: DomainRef,
        limits: EnvironmentLimits,
        **kwargs: object,
    ) -> ProbeEvidence:
        assert kwargs["environment_helper_sha256"] == asset.digest
        assert asset.backend._environment_helper(asset.digest) == asset.installed
        calls.append(operation)
        if operation is TrustedPythonOperation.CREATE_ENVIRONMENT:
            fd = kwargs["export_fd"]
            assert isinstance(fd, int)
            os.write(fd, b"bounded fixture export")
        return identity_probe().model_copy(
            update=dict(operation_id=operation_id, probe=operation, limits=limits)
        )

    monkeypatch.setattr(asset.backend, "_run_operation", closed)

    async def run() -> None:
        await asset.backend.run_environment_create(
            configured, DomainRef("build-asset"), tmp_path / "export", asset.digest
        )
        assert (tmp_path / "export").read_bytes() == b"bounded fixture export"
        await asset.backend.run_environment_verify(
            configured, DomainRef("verify-asset"), tmp_path / "venv", asset.digest
        )

    asyncio.run(run())
    assert calls == [
        TrustedPythonOperation.CREATE_ENVIRONMENT,
        TrustedPythonOperation.VERIFY_ENVIRONMENT,
    ]


@pytest.mark.parametrize("operation", ["create", "verify"])
def test_post_operation_helper_drift_cannot_yield_success(
    asset: AssetCase,
    configured: PythonDistributionConfiguration,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    async def drift_after_launch(*args: object, **kwargs: object) -> ProbeEvidence:
        asset.installed.chmod(0o644)
        asset.installed.write_bytes(b"changed after launch\n")
        asset.installed.chmod(0o444)
        return identity_probe()

    monkeypatch.setattr(asset.backend, "_run_operation", drift_after_launch)

    async def run() -> None:
        with pytest.raises(RuntimeConfinementUnavailable):
            if operation == "create":
                await asset.backend.run_environment_create(
                    configured, DomainRef("build-asset"), tmp_path / "export", asset.digest
                )
            else:
                await asset.backend.run_environment_verify(
                    configured, DomainRef("verify-asset"), tmp_path / "venv", asset.digest
                )

    asyncio.run(run())


def test_helper_parent_failure_has_closed_confinement_diagnostic(asset: AssetCase) -> None:
    # Drift a separate ancestor, not the file or immediate containing directory.
    asset.installed.parent.parent.chmod(0o775)
    with pytest.raises(RuntimeConfinementUnavailable) as error:
        asset.backend._environment_helper(asset.digest)
    assert error.value.stage is ConfinementFailureStage.HELPER_PARENT_TRUST
    assert error.value.failure.runtime_reason is None
    assert error.value.failure.reason_code is PreparationReasonCode.CONFINEMENT_UNAVAILABLE


def test_existing_native_helper_trust_does_not_allow_checkout_modes(asset: AssetCase) -> None:
    native = asset.installed.parent / "native-helper"
    native.chmod(0o775)
    with pytest.raises(RuntimeConfinementUnavailable):
        _trusted_tool(
            asset.backend._tools,
            asset.backend.configuration.helper_tool,
            asset.backend.configuration.helper_sha256,
            static_elf=True,
        )


def test_real_parent_check_still_rejects_shared_tmp() -> None:
    # Unlike the portable fixture, production grants no sticky-parent exception.
    with pytest.raises(ProvenanceFailure):
        _parents(Path("/tmp"))
