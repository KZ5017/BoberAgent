"""C4 manual harness tested only against temporary synthetic retained Core data."""

from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest
from boberagent_contracts import PoCAcquisitionRef
from boberagent_core import CoreDatabase
from boberagent_core.acquisitions import CorePoCAcquisitionService
from boberagent_core.artifacts import CoreArtifactService
from boberagent_core.inspections import (
    CorePoCInspectionService,
    CorePoCSupportClassificationService,
    InspectionStatus,
    PoCInspection,
    PoCInspectionRef,
    SupportClassification,
    SupportClassificationDocument,
)
from test_poc_inspection_c2 import completed_document, fixture_repository, prepare
from test_poc_inspection_c3 import CHECKER
from test_poc_inspection_c41_history import seed_legacy_history


def _smoke() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[3]
        / "scripts/manual-smoke/m20c4_real_retained_source_inspection_smoke_test.py"
    )
    spec = importlib.util.spec_from_file_location("m20c4_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _arguments(
    database_path: Path, acquisition_ref: PoCAcquisitionRef, *, real: bool = False
) -> list[str]:
    return [
        "--real-retained-source" if real else "--check-config",
        "--database",
        str(database_path),
        "--artifact-root",
        str(database_path.parent / "artifacts"),
        "--acquisition-ref",
        str(acquisition_ref),
    ]


def _forbidden(*args: object, **kwargs: object) -> None:
    raise AssertionError("C4 must not perform network, execution, extraction or installation")


@pytest.fixture
def no_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(zipfile.ZipFile, "extract", _forbidden)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", _forbidden)


@pytest.mark.usefixtures("no_execution")
def test_current_smoke_preserves_legacy_history(
    database: CoreDatabase,
    database_path: Path,
    tmp_path: Path,
) -> None:
    module = _smoke()
    service, request = prepare(
        database, tmp_path, {"checker.py": CHECKER + b'\nimport os\nos.unlink("scratch.txt")\n'}
    )
    current, _ = completed_document(service, request)
    old_c2, old_c3 = seed_legacy_history(database, current)
    before = (old_c2.model_dump_json(), old_c3.model_dump_json())
    history = module._run(
        module._parser().parse_args(_arguments(database_path, request.acquisition_ref, real=True))
    )
    assert history.c2.profile_version == history.c3.profile_version == "2"
    assert history.c2.inspection_ref != old_c2.inspection_ref
    assert history.c3.inspection_ref != old_c3.inspection_ref
    assert isinstance(history.c3.document, SupportClassificationDocument)
    assert history.c3.document.classification is SupportClassification.ASSISTED
    for ref, snapshot in zip((old_c2.inspection_ref, old_c3.inspection_ref), before, strict=True):
        stored = service.get(ref)
        assert stored is not None and stored.model_dump_json() == snapshot


def test_opt_in_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    module = _smoke()
    with pytest.raises(SystemExit) as missing:
        module._parser().parse_args([])
    assert missing.value.code == 2
    with pytest.raises(SystemExit) as help_exit:
        module._parser().parse_args(["--help"])
    assert help_exit.value.code == 0
    output = capsys.readouterr().out
    assert "--real-retained-source" in output and "--check-config" in output
    assert "--endpoint" not in output and "--node-id" not in output


@pytest.mark.usefixtures("no_execution")
def test_preflight_no_mutation_or_source_reads(
    database: CoreDatabase,
    database_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _smoke()
    service, request = prepare(database, tmp_path, {"checker.py": CHECKER})
    before_history = service.list_for_acquisition(request.acquisition_ref)
    database.dispose()
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(CoreArtifactService, "open_content", _forbidden)
    monkeypatch.setattr(CorePoCInspectionService, "create", _forbidden)
    monkeypatch.setattr(module.FilesystemArtifactStorage, "__init__", _forbidden)
    monkeypatch.setattr(module, "upgrade_database", _forbidden)
    assert module.main(_arguments(database_path, request.acquisition_ref)) == 0
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert service.list_for_acquisition(request.acquisition_ref) == before_history
    output = capsys.readouterr().out
    assert "OFFLINE RETAINED-SOURCE CONFIGURATION VALID" in output
    assert "m20-c1-evidence@1" in output and "m20-c3-support-classifier@2" in output


@pytest.mark.parametrize(
    ("flag", "value", "diagnostic"),
    [
        ("--expected-raw-sha256", "b" * 64, "EXPECTED_RAW_SHA256_MISMATCH"),
        ("--expected-manifest-sha256", "b" * 64, "EXPECTED_MANIFEST_SHA256_MISMATCH"),
        ("--expected-raw-artifact-ref", "artifact-wrong", "EXPECTED_RAW_ARTIFACT_REF_MISMATCH"),
        (
            "--expected-manifest-artifact-ref",
            "artifact-wrong",
            "EXPECTED_MANIFEST_ARTIFACT_REF_MISMATCH",
        ),
        ("--expected-commit", "b" * 40, "EXPECTED_COMMIT_MISMATCH"),
    ],
)
def test_expected_identity_rejected(
    database: CoreDatabase,
    database_path: Path,
    tmp_path: Path,
    flag: str,
    value: str,
    diagnostic: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _smoke()
    service, request = prepare(database, tmp_path, {"checker.py": CHECKER})
    before = service.list_for_acquisition(request.acquisition_ref)
    assert module.main([*_arguments(database_path, request.acquisition_ref), flag, value]) == 2
    assert diagnostic in capsys.readouterr().err
    assert service.list_for_acquisition(request.acquisition_ref) == before


def test_missing_state_stops_without_recreating(
    database: CoreDatabase,
    database_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _smoke()
    _, request = prepare(database, tmp_path, {"checker.py": CHECKER})
    assert module.main(_arguments(database_path, PoCAcquisitionRef("poc-acquisition-missing"))) == 2
    assert "ACQUISITION_NOT_FOUND" in capsys.readouterr().err
    args = _arguments(database_path, request.acquisition_ref)
    args[args.index("--artifact-root") + 1] = str(tmp_path / "missing-root")
    assert module.main(args) == 2
    assert "MISSING_ARTIFACT_ROOT" in capsys.readouterr().err
    assert not (tmp_path / "missing-root").exists()
    assert module.main(_arguments(tmp_path / "missing.sqlite3", request.acquisition_ref)) == 2
    assert "MISSING_DATABASE" in capsys.readouterr().err
    assert not (tmp_path / "missing.sqlite3").exists()


def test_non_completed_acquisition_rejected(
    database: CoreDatabase,
    database_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _smoke()
    _, request = prepare(database, tmp_path, {"checker.py": CHECKER})
    with database.unit_of_work() as work:
        completed = work.acquisitions.get(request.acquisition_ref)
    assert completed is not None
    artifacts, _ = module._services(database, tmp_path / "artifacts")
    pending = CorePoCAcquisitionService(database, artifacts).create_acquisition(
        mission_ref=completed.mission_ref,
        hypothesis_ref=completed.hypothesis_ref,
        candidate_ref=completed.candidate_ref,
        selected_hit_id=completed.selected_hit_id,
        bounds=completed.bounds,
    )
    assert module.main(_arguments(database_path, pending.acquisition_ref)) == 2
    assert "ACQUISITION_NOT_COMPLETED" in capsys.readouterr().err


@pytest.mark.usefixtures("no_execution")
@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (b"", SupportClassification.AUTOMATIC),
        (b'\nopen("report.txt", "w")\n', SupportClassification.ASSISTED),
        (b"\nimport os\nos.unlink(dynamic_path)\n", SupportClassification.UNSUPPORTED),
        (b'\nparser.add_argument("--password", required=True)\n', SupportClassification.ASSISTED),
        (b'\nimport shutil\nshutil.rmtree("/")\n', SupportClassification.UNSUPPORTED),
    ],
)
def test_production_pipeline_reopen_and_reuse_accepts_all_classifications(
    database: CoreDatabase,
    database_path: Path,
    tmp_path: Path,
    extra: bytes,
    expected: SupportClassification,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _smoke()
    original, request = prepare(database, tmp_path, {"checker.py": CHECKER + extra})
    before = original.list_for_acquisition(request.acquisition_ref)
    original_inspect = CorePoCInspectionService.inspect
    original_classify = CorePoCSupportClassificationService.classify
    calls: list[str] = []

    def inspect(self: CorePoCInspectionService, ref: PoCInspectionRef) -> PoCInspection:
        stored = self.get(ref)
        calls.append(stored.profile_id if stored is not None else "missing")
        return original_inspect(self, ref)

    def classify(self: CorePoCSupportClassificationService, ref: PoCInspectionRef) -> PoCInspection:
        calls.append("m20-c3-support-classifier")
        return original_classify(self, ref)

    # Observe calls, never substitute semantic results.
    monkeypatch.setattr(CorePoCInspectionService, "inspect", inspect)
    monkeypatch.setattr(CorePoCSupportClassificationService, "classify", classify)
    args = module._parser().parse_args(
        _arguments(database_path, request.acquisition_ref, real=True)
    )
    history = module._run(args)
    assert isinstance(history.c3.document, SupportClassificationDocument)
    assert history.c3.document.classification is expected
    assert all(
        item.status is InspectionStatus.COMPLETED for item in (history.c1, history.c2, history.c3)
    )
    after = original.list_for_acquisition(request.acquisition_ref)
    assert len(after) == len(before) + 2  # Requested C2 is reused; C1/C3 are distinct.
    assert module._run(args) == history
    assert original.list_for_acquisition(request.acquisition_ref) == after
    output = capsys.readouterr().out
    assert (
        "unchanged after Core reopen" in output and "identical invocation reused history" in output
    )
    assert f"C3 classification: {expected.value}" in output
    assert "Citation spot check:" in output and "span_sha256=" in output
    assert "NOT authorization or safety" in output
    assert calls.count("m20-c1-evidence") == 4
    assert calls.count("m20-c2-deterministic") == 4
    assert calls.count("m20-c3-support-classifier") == 4


@pytest.mark.usefixtures("no_execution")
def test_safe_multi_extractor_output(
    database: CoreDatabase,
    database_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _smoke()
    files = fixture_repository()
    marker = b"harmless-password-must-not-appear"
    files["checker.py"] = (
        CHECKER + b'\nparser.add_argument("--password", default="' + marker + b'")\n'
    )
    _, request = prepare(database, tmp_path, files)
    assert module.main(_arguments(database_path, request.acquisition_ref, real=True)) == 0
    output = capsys.readouterr().out
    assert marker.decode() not in output
    assert "<REDACTED>" in output
    assert "DOCUMENTATION/OBSERVED" in output
    assert "CODE/OBSERVED" in output
    assert "SKIPPED_UNSUPPORTED_TYPE" in output and "image.png" in output
    assert "python-ast" in output and "powershell-lexical" in output and "shell-lexical" in output
    checks = [line for line in output.splitlines() if line.startswith("Citation spot check:")]
    assert any("python-ast" in line for line in checks)
    assert any("powershell-lexical" in line for line in checks)
    assert any("shell-lexical" in line for line in checks)
    assert any("documentation-claims" in line for line in checks)
    assert "Unknowns" in output and "Conflicts" in output


@pytest.mark.usefixtures("no_execution")
def test_cached_history_does_not_mask_changed_artifact_bytes(
    database: CoreDatabase,
    database_path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _smoke()
    service, request = prepare(database, tmp_path, {"checker.py": CHECKER})
    args = _arguments(database_path, request.acquisition_ref, real=True)
    assert module.main(args) == 0
    before = service.list_for_acquisition(request.acquisition_ref)
    selection = module._preflight(module._parser().parse_args(args))
    receipt = selection.acquisition.receipt
    assert receipt is not None
    digest = receipt.raw_archive_sha256
    path = tmp_path / "artifacts/content/sha256" / digest[:2] / f"{digest}.blob"
    original = path.read_bytes()
    path.write_bytes(b"X" + original[1:])  # Test-owned corruption, same declared size.
    assert module.main(args) == 2
    assert "RETAINED_ARTIFACT_INTEGRITY_MISMATCH" in capsys.readouterr().err
    assert service.list_for_acquisition(request.acquisition_ref) == before


def test_reopen_mismatch_is_not_reported_as_success(
    database: CoreDatabase,
    database_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _smoke()
    _, request = prepare(database, tmp_path, {"checker.py": CHECKER})
    original_preflight = module._preflight
    original_get = CorePoCInspectionService.get
    preflights = 0

    def preflight(args: object) -> object:
        nonlocal preflights
        selection = original_preflight(args)
        preflights += 1
        return selection

    def get(self: CorePoCInspectionService, ref: PoCInspectionRef) -> PoCInspection | None:
        return None if preflights > 1 else original_get(self, ref)

    monkeypatch.setattr(module, "_preflight", preflight)
    monkeypatch.setattr(CorePoCInspectionService, "get", get)
    assert module.main(_arguments(database_path, request.acquisition_ref, real=True)) == 2
    assert "INSPECTION_CHANGED_AFTER_REOPEN" in capsys.readouterr().err


def test_reuse_history_growth_is_rejected(
    database: CoreDatabase,
    database_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _smoke()
    _, request = prepare(database, tmp_path, {"checker.py": CHECKER})
    original = CorePoCInspectionService.list_for_acquisition
    reads = 0

    def changed(
        self: CorePoCInspectionService, ref: PoCAcquisitionRef
    ) -> tuple[PoCInspection, ...]:
        nonlocal reads
        reads += 1
        history = original(self, ref)
        return history if reads == 1 else (*history, history[0])

    monkeypatch.setattr(CorePoCInspectionService, "list_for_acquisition", changed)
    assert module.main(_arguments(database_path, request.acquisition_ref, real=True)) == 2
    assert "INSPECTION_HISTORY_CHANGED_ON_REUSE" in capsys.readouterr().err
