"""D8 manual harness acceptance against migrated, synthetic retained evidence only."""

import sqlite3
import subprocess
import sys
from pathlib import Path

from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_core import (
    ArtifactStorageConfiguration,
    CoreArtifactService,
    CoreDatabase,
    FilesystemArtifactStorage,
)
from boberagent_core.inspections import CorePoCInspectionService
from boberagent_core.inspections.classification_models import (
    SupportClassification,
    SupportClassificationDocument,
)
from boberagent_core.planning import PlanningAttemptLifecycle, PlanningDisposition
from boberagent_core.planning.admission import CorePlanningAdmissionService
from boberagent_core.planning.fingerprints import planning_request_fingerprint
from planning_admission_fixtures import AdmissionChain, seed_chain
from test_poc_inspection_c3 import CHECKER

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/manual-smoke/m20d8_real_retained_negative_planning_smoke_test.py"


def _chain(database: CoreDatabase, tmp_path: Path) -> AdmissionChain:
    chain = seed_chain(
        database,
        tmp_path,
        {
            "checker.py": CHECKER
            + b'\nparser.add_argument("--password", required=True)\nunknown.connect()\n',
            "helper.bin": b"\x00\xff",
            "source.py": b"print('synthetic fixture')\n",
            "README.md": b"No credentials required.\n",
        },
    )
    assert isinstance(chain.c3.document, SupportClassificationDocument)
    assert chain.c3.document.classification is SupportClassification.UNSUPPORTED
    assert chain.acquisition.receipt is not None

    with database.unit_of_work() as work:
        c1 = next(
            item
            for item in work.inspections.list_for_acquisition(chain.acquisition.acquisition_ref)
            if item.profile_id == "m20-c1-evidence"
        )
    completed = CorePoCInspectionService(
        database,
        CoreArtifactService(
            database,
            FilesystemArtifactStorage(ArtifactStorageConfiguration(root=tmp_path / "artifacts")),
        ),
    ).inspect(c1.inspection_ref)
    assert completed.status.value == "COMPLETED", completed.diagnostic
    return chain


def _args(database: CoreDatabase, tmp_path: Path, chain: AdmissionChain) -> list[str]:
    receipt = chain.acquisition.receipt
    classification = chain.c3.document
    assert receipt is not None
    assert isinstance(classification, SupportClassificationDocument)
    with database.unit_of_work() as work:
        c1 = next(
            item
            for item in work.inspections.list_for_acquisition(chain.acquisition.acquisition_ref)
            if item.profile_id == "m20-c1-evidence"
        )
    values = [
        "--database",
        str(tmp_path / "core.sqlite3"),
        "--artifact-root",
        str(tmp_path / "artifacts"),
        "--mission-ref",
        str(chain.request.mission_ref),
        "--candidate-ref",
        str(chain.acquisition.candidate_ref),
        "--acquisition-ref",
        str(chain.acquisition.acquisition_ref),
        "--c1-inspection-ref",
        str(c1.inspection_ref),
        "--c2-inspection-ref",
        str(chain.c2.inspection_ref),
        "--c3-inspection-ref",
        str(chain.c3.inspection_ref),
        "--raw-artifact-ref",
        str(receipt.raw_source.artifact_id),
        "--raw-sha256",
        receipt.raw_archive_sha256,
        "--manifest-artifact-ref",
        str(receipt.manifest.artifact_id),
        "--manifest-sha256",
        receipt.manifest_sha256,
        "--commit",
        receipt.resolved_commit_sha,
    ]
    for reason in classification.reasons:
        values.extend(("--expected-reason-code", reason.code.value))
    return values


def _invoke(mode: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), mode, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        return {
            name: int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if name != "sqlite_sequence"
        }


def test_offline_retained_negative_preflight_reopen_and_reuse(
    database: CoreDatabase, tmp_path: Path
) -> None:
    chain = _chain(database, tmp_path)
    args = _args(database, tmp_path, chain)
    path = tmp_path / "core.sqlite3"
    before = _counts(path)
    preflight = _invoke("--check-config", args)
    assert preflight.returncode == 0, preflight.stderr
    assert "read-only retained metadata preflight" in preflight.stdout
    assert _counts(path) == before

    first = _invoke("--real-retained-source", args)
    assert first.returncode == 0, first.stderr
    assert "COMPLETED/UNSUPPORTED/REJECTED_UNSUPPORTED" in first.stdout
    assert '"execution_plans": 0' in first.stdout
    assert '"plan_decisions": 0' in first.stdout
    assert '"interactions": 0' in first.stdout
    classification = chain.c3.document
    assert isinstance(classification, SupportClassificationDocument)
    assert canonical_digest(classification) in first.stdout
    assert all(reason.code.value in first.stdout for reason in classification.reasons)
    after = _counts(path)
    assert after == before | {"planning_attempts": before["planning_attempts"] + 1}

    # The smoke itself reopens Core and re-admits. A second operator invocation reuses it too.
    second = _invoke("--real-retained-source", args)
    assert second.returncode == 0, second.stderr
    assert _counts(path) == after
    assert first.stdout == second.stdout
    with database.unit_of_work() as work:
        history = work.inspections.list_for_acquisition(chain.acquisition.acquisition_ref)
        assert chain.c2 in history and chain.c3 in history
        assert work.acquisitions.get(chain.acquisition.acquisition_ref) == chain.acquisition
    service = CorePlanningAdmissionService(database)
    result = service.admit(chain.request)
    assert result.attempt.lifecycle is PlanningAttemptLifecycle.COMPLETED
    assert result.attempt.disposition is PlanningDisposition.UNSUPPORTED
    assert result.attempt.request.inspection.classification == classification
    assert result.attempt.request.inspection.classification_sha256 == canonical_digest(
        classification
    )
    assert result.attempt.revisions == ()
    assert result.attempt.finalized_plan is None
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        fingerprint = connection.execute(
            "SELECT request_fingerprint FROM planning_attempts WHERE attempt_id = ?",
            (str(result.attempt.planning_attempt_ref),),
        ).fetchone()
    assert fingerprint == (planning_request_fingerprint(result.attempt.request),)


def test_preflight_rejects_wrong_identity_without_writes(
    database: CoreDatabase, tmp_path: Path
) -> None:
    chain = _chain(database, tmp_path)
    args = _args(database, tmp_path, chain)
    before = _counts(tmp_path / "core.sqlite3")
    wrong = args.copy()
    wrong[wrong.index("--raw-sha256") + 1] = "0" * 64
    result = _invoke("--check-config", wrong)
    assert result.returncode == 2
    assert "EXPECTED_SOURCE_IDENTITY_MISMATCH" in result.stderr
    assert "Traceback" not in result.stderr
    assert _counts(tmp_path / "core.sqlite3") == before
