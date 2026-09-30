"""Opt-in, offline D3 negative admission of already retained C2@2/C3@2 evidence.

Preflight is metadata-only and read-only. The real mode creates at most one Core
PlanningAttempt; it never opens source bytes or invokes construction/execution.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from boberagent_contracts import ArtifactRef, MissionRef, PoCAcquisitionRef
from boberagent_contracts.plan_canonical import canonical_digest
from boberagent_core.acquisitions.models import PoCAcquisition, PoCAcquisitionStatus
from boberagent_core.inspections.classification_models import (
    SupportClassification,
    SupportClassificationDocument,
    semantic_digest,
)
from boberagent_core.inspections.identity import PoCInspectionRef
from boberagent_core.inspections.models import InspectionStatus, PoCInspection
from boberagent_core.inspections.semantic_models import SemanticInspectionDocument
from boberagent_core.models import StoredArtifact
from boberagent_core.persistence import CoreDatabase, DatabaseConfig
from boberagent_core.persistence.migrations import current_revision, head_revision
from boberagent_core.planning.admission import CorePlanningAdmissionService
from boberagent_core.planning.admission_models import (
    PlanningAdmissionOutcome,
    PlanningAdmissionRequest,
)
from boberagent_core.planning.fingerprints import planning_request_fingerprint
from boberagent_core.planning.models import PlanningAttemptLifecycle, PlanningDisposition
from boberagent_core.research.models import PoCCandidateRef


class SmokeStop(RuntimeError):
    """A bounded operator diagnostic; never render source or database exception text."""


@dataclass(frozen=True)
class Config:
    database: Path
    artifact_root: Path
    mission_ref: MissionRef
    candidate_ref: PoCCandidateRef
    acquisition_ref: PoCAcquisitionRef
    c1_ref: PoCInspectionRef
    c2_ref: PoCInspectionRef
    c3_ref: PoCInspectionRef
    raw_ref: ArtifactRef
    raw_sha256: str
    manifest_ref: ArtifactRef
    manifest_sha256: str
    commit: str
    required_reason_codes: frozenset[str]


@dataclass(frozen=True)
class Retained:
    acquisition: PoCAcquisition
    c1: PoCInspection
    c2: PoCInspection
    c3: PoCInspection
    history: tuple[PoCInspection, ...]
    raw_catalog: StoredArtifact
    manifest_catalog: StoredArtifact


_KNOWN_BLOCKERS = frozenset(
    {
        "UNSUPPORTED_INSUFFICIENT_COVERAGE",
        "UNSUPPORTED_MATERIAL_UNKNOWN",
        "UNSUPPORTED_TARGET_BOUNDARY",
    }
)
_REAL_ACQUISITION = PoCAcquisitionRef("poc-acquisition-2f6a3658a57c42f5ae2252edf1736352")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-config", action="store_true", help="read-only metadata preflight")
    mode.add_argument(
        "--real-retained-source", action="store_true", help="opt in to one D3 admission"
    )
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--mission-ref", required=True, type=MissionRef)
    parser.add_argument("--candidate-ref", required=True, type=PoCCandidateRef)
    parser.add_argument("--acquisition-ref", required=True, type=PoCAcquisitionRef)
    parser.add_argument("--c1-inspection-ref", required=True, type=PoCInspectionRef)
    parser.add_argument("--c2-inspection-ref", required=True, type=PoCInspectionRef)
    parser.add_argument("--c3-inspection-ref", required=True, type=PoCInspectionRef)
    parser.add_argument("--raw-artifact-ref", required=True, type=ArtifactRef)
    parser.add_argument("--raw-sha256", required=True)
    parser.add_argument("--manifest-artifact-ref", required=True, type=ArtifactRef)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument(
        "--expected-reason-code",
        action="append",
        help="add an expected reason code (synthetic offline fixtures may specify their own)",
    )
    return parser


def _config(args: argparse.Namespace) -> Config:
    if not args.database.is_absolute() or not args.database.is_file():
        raise SmokeStop("MISSING_DATABASE")
    if not args.artifact_root.is_absolute() or not args.artifact_root.is_dir():
        raise SmokeStop("MISSING_ARTIFACT_ROOT")
    return Config(
        database=args.database.resolve(),
        artifact_root=args.artifact_root.resolve(),
        mission_ref=args.mission_ref,
        candidate_ref=args.candidate_ref,
        acquisition_ref=args.acquisition_ref,
        c1_ref=args.c1_inspection_ref,
        c2_ref=args.c2_inspection_ref,
        c3_ref=args.c3_inspection_ref,
        raw_ref=args.raw_artifact_ref,
        raw_sha256=args.raw_sha256,
        manifest_ref=args.manifest_artifact_ref,
        manifest_sha256=args.manifest_sha256,
        commit=args.commit,
        required_reason_codes=frozenset(args.expected_reason_code or ())
        | (_KNOWN_BLOCKERS if args.acquisition_ref == _REAL_ACQUISITION else frozenset()),
    )


def _readonly(path: Path) -> CoreDatabase:
    # A SQLite read-only URI prevents even an accidental repository write in preflight.
    return CoreDatabase(DatabaseConfig(url=f"sqlite+pysqlite:///{path.as_uri()}?mode=ro&uri=true"))


def _retained(config: Config) -> Retained:
    database = _readonly(config.database)
    try:
        if current_revision(database) != head_revision():
            raise SmokeStop("CORE_SCHEMA_NOT_CURRENT")
        with database.unit_of_work() as work:
            mission = work.missions.get(config.mission_ref)
            acquisition = work.acquisitions.get(config.acquisition_ref)
            c1 = work.inspections.get(config.c1_ref)
            c2 = work.inspections.get(config.c2_ref)
            c3 = work.inspections.get(config.c3_ref)
            if mission is None or acquisition is None or c1 is None or c2 is None or c3 is None:
                raise SmokeStop("RETAINED_CHAIN_NOT_FOUND")
            receipt = acquisition.receipt
            if (
                acquisition.status is not PoCAcquisitionStatus.COMPLETED
                or receipt is None
                or acquisition.mission_ref != config.mission_ref
                or acquisition.candidate_ref != config.candidate_ref
            ):
                raise SmokeStop("ACQUISITION_IDENTITY_OR_STATUS_MISMATCH")
            if (
                receipt.raw_source.artifact_id != config.raw_ref
                or receipt.raw_archive_sha256 != config.raw_sha256
                or receipt.manifest.artifact_id != config.manifest_ref
                or receipt.manifest_sha256 != config.manifest_sha256
                or receipt.resolved_commit_sha != config.commit
            ):
                raise SmokeStop("EXPECTED_SOURCE_IDENTITY_MISMATCH")
            raw = work.artifacts.get_record(config.raw_ref)
            manifest = work.artifacts.get_record(config.manifest_ref)
            if (
                raw is None
                or manifest is None
                or not raw.content_available
                or not manifest.content_available
                or raw.descriptor != receipt.raw_source
                or manifest.descriptor != receipt.manifest
            ):
                raise SmokeStop("ARTIFACT_CATALOG_MISMATCH")
            for record, profile, version in (
                (c1, "m20-c1-evidence", "1"),
                (c2, "m20-c2-deterministic", "2"),
                (c3, "m20-c3-support-classifier", "2"),
            ):
                if (
                    record.status is not InspectionStatus.COMPLETED
                    or record.profile_id != profile
                    or record.profile_version != version
                    or record.acquisition_ref != acquisition.acquisition_ref
                    or record.mission_ref != mission.mission_ref
                ):
                    raise SmokeStop("INSPECTION_IDENTITY_OR_STATUS_MISMATCH")
            if not isinstance(c2.document, SemanticInspectionDocument) or not isinstance(
                c3.document, SupportClassificationDocument
            ):
                raise SmokeStop("INSPECTION_DOCUMENT_INVALID")
            if (
                c3.document.classification is not SupportClassification.UNSUPPORTED
                or c3.document.semantic_inspection_ref != c2.inspection_ref
                or c3.document.semantic_document_sha256 != semantic_digest(c2.document)
            ):
                raise SmokeStop("C3_CLASSIFICATION_OR_PARENT_MISMATCH")
            history = work.inspections.list_for_acquisition(acquisition.acquisition_ref)
            codes = {reason.code.value for reason in c3.document.reasons}
            if not codes >= config.required_reason_codes:
                raise SmokeStop("EXPECTED_C3_BLOCKERS_MISSING")
            return Retained(acquisition, c1, c2, c3, history, raw, manifest)
    finally:
        database.dispose()


def _counts(path: Path) -> dict[str, int]:
    # Acceptance instrumentation only. The Core service still owns every write.
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        tables = (
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row[0] != "sqlite_sequence"
        )
        return {
            name: int(
                connection.execute(
                    f'SELECT COUNT(*) FROM "{name.replace(chr(34), chr(34) * 2)}"'
                ).fetchone()[0]
            )
            for name in tables
        }


def _attempt_counts(path: Path, attempt_ref: str) -> dict[str, int]:
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        return {
            "execution_plans": int(
                connection.execute(
                    "SELECT COUNT(*) FROM execution_plans WHERE attempt_id = ?", (attempt_ref,)
                ).fetchone()[0]
            ),
            "plan_decisions": int(
                connection.execute(
                    "SELECT COUNT(*) FROM plan_decisions AS d "
                    "JOIN execution_plans AS p ON d.plan_id = p.plan_id WHERE p.attempt_id = ?",
                    (attempt_ref,),
                ).fetchone()[0]
            ),
            "interactions": int(
                connection.execute(
                    "SELECT COUNT(*) FROM interactions WHERE planning_attempt_id = ?",
                    (attempt_ref,),
                ).fetchone()[0]
            ),
        }


def _fingerprint(path: Path, attempt_ref: str) -> str:
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT request_fingerprint FROM planning_attempts WHERE attempt_id = ?",
            (attempt_ref,),
        ).fetchone()
    if row is None:
        raise SmokeStop("PLANNING_ATTEMPT_NOT_DURABLE")
    return str(row[0])


def _negative(
    result: object, retained: Retained, path: Path, required_codes: frozenset[str]
) -> tuple[str, str]:
    from boberagent_core.planning.admission_models import PlanningAdmissionResult

    if not isinstance(result, PlanningAdmissionResult):
        raise SmokeStop("ADMISSION_RESULT_INVALID")
    attempt = result.attempt
    c3 = retained.c3.document
    assert isinstance(c3, SupportClassificationDocument)
    if (
        result.outcome is not PlanningAdmissionOutcome.REJECTED_UNSUPPORTED
        or attempt.lifecycle is not PlanningAttemptLifecycle.COMPLETED
        or attempt.disposition is not PlanningDisposition.UNSUPPORTED
        or attempt.request.inspection.classification_ref != retained.c3.inspection_ref
        or attempt.request.inspection.classification != c3
        or attempt.request.inspection.classification_sha256 != canonical_digest(c3)
        or attempt.revisions
        or attempt.request.proposal is not None
        or attempt.finalized_plan is not None
    ):
        raise SmokeStop("D3_NEGATIVE_BOUNDARY_INVALID")
    codes = {reason.code.value for reason in c3.reasons}
    if not codes >= required_codes:
        raise SmokeStop("EXPECTED_C3_BLOCKERS_MISSING")
    attempt_ref = str(attempt.planning_attempt_ref)
    if any(_attempt_counts(path, attempt_ref).values()):
        raise SmokeStop("DOWNSTREAM_PLANNING_RECORD_CREATED")
    fingerprint = _fingerprint(path, attempt_ref)
    if fingerprint != planning_request_fingerprint(attempt.request):
        raise SmokeStop("PLANNING_FINGERPRINT_MISMATCH")
    return attempt_ref, fingerprint


def _summary(retained: Retained, result: object, fingerprint: str, path: Path) -> None:
    from boberagent_core.planning.admission_models import PlanningAdmissionResult

    assert isinstance(result, PlanningAdmissionResult)
    c2 = retained.c2.document
    c3 = retained.c3.document
    assert isinstance(c2, SemanticInspectionDocument)
    assert isinstance(c3, SupportClassificationDocument)
    attempt = result.attempt
    print(f"MissionRef: {attempt.request.mission_ref}")
    print(f"PoCAcquisitionRef: {retained.acquisition.acquisition_ref}")
    print(
        f"C2: {retained.c2.inspection_ref} {retained.c2.profile_id}@{retained.c2.profile_version} digest={semantic_digest(c2)}"
    )
    print(
        f"C3: {retained.c3.inspection_ref} {retained.c3.profile_id}@{retained.c3.profile_version} digest={canonical_digest(c3)}"
    )
    print(f"PlanningAttemptRef: {attempt.planning_attempt_ref}")
    print(f"Request fingerprint: {fingerprint}")
    print(
        f"Lifecycle/disposition/admission: {attempt.lifecycle.value}/{attempt.disposition.value if attempt.disposition else 'NONE'}/{result.outcome.value}"
    )
    for reason in c3.reasons:
        # Reason references are bounded IDs/paths from persisted classification, not excerpts.
        print(
            json.dumps(
                {
                    "reason": reason.code.value,
                    "item_refs": reason.item_refs,
                    "conflict_refs": reason.conflict_refs,
                    "coverage_paths": reason.coverage_paths,
                },
                sort_keys=True,
            )
        )
    print(
        json.dumps(
            {
                "blocking_unknown_refs": c3.blocking_unknown_refs,
                "blocking_conflict_refs": c3.blocking_conflict_refs,
                "assistance_unknown_refs": c3.assistance_unknown_refs,
            },
            sort_keys=True,
        )
    )
    print(json.dumps(_attempt_counts(path, str(attempt.planning_attempt_ref)), sort_keys=True))


def _run(config: Config, *, real: bool) -> None:
    retained = _retained(config)
    c2 = retained.c2.document
    c3 = retained.c3.document
    assert isinstance(c2, SemanticInspectionDocument)
    assert isinstance(c3, SupportClassificationDocument)
    print(
        f"Preflight: C2={retained.c2.inspection_ref} digest={semantic_digest(c2)} C3={retained.c3.inspection_ref} digest={canonical_digest(c3)} classification={c3.classification.value}"
    )
    if not real:
        print("PASS: read-only retained metadata preflight; no source bytes or PlanningAttempt")
        return
    baseline = _counts(config.database)
    request = PlanningAdmissionRequest(
        mission_ref=config.mission_ref,
        acquisition_ref=config.acquisition_ref,
        semantic_inspection_ref=config.c2_ref,
        classification_inspection_ref=config.c3_ref,
        planner_profile="m20-d-planning",
        planner_version="1",
        policy_profile="m20-python-single-target",
        policy_version="1",
    )
    database = CoreDatabase(DatabaseConfig.sqlite(config.database))
    try:
        service = CorePlanningAdmissionService(database)
        result = service.admit(request)
        attempt_ref, fingerprint = _negative(
            result, retained, config.database, config.required_reason_codes
        )
        if service.get_admission(result.attempt.planning_attempt_ref) != result:
            raise SmokeStop("D3_DURABLE_READ_MISMATCH")
    finally:
        database.dispose()
    after_first = _counts(config.database)
    expected = baseline | {
        "planning_attempts": baseline["planning_attempts"]
        + (0 if _fingerprint_preexisted(baseline, after_first) else 1)
    }
    if after_first != expected:
        raise SmokeStop("UNEXPECTED_DATABASE_SIDE_EFFECT")
    if _retained(config) != retained:
        raise SmokeStop("UPSTREAM_HISTORY_CHANGED")
    reopened = CoreDatabase(DatabaseConfig.sqlite(config.database))
    try:
        service = CorePlanningAdmissionService(reopened)
        if service.get_admission(result.attempt.planning_attempt_ref) != result:
            raise SmokeStop("REOPENED_ATTEMPT_MISMATCH")
        reused = service.admit(request)
        if reused != result or _negative(
            reused, retained, config.database, config.required_reason_codes
        ) != (attempt_ref, fingerprint):
            raise SmokeStop("IDENTICAL_ADMISSION_NOT_REUSED")
    finally:
        reopened.dispose()
    if _counts(config.database) != after_first or _retained(config) != retained:
        raise SmokeStop("REPLAY_CHANGED_DURABLE_STATE")
    _summary(retained, result, fingerprint, config.database)
    print(
        "PASS: reopen and identical admission reuse; no plan, validation, policy, HITL, approval or execution-side records"
    )


def _fingerprint_preexisted(before: dict[str, int], after: dict[str, int]) -> bool:
    if after["planning_attempts"] == before["planning_attempts"]:
        return True
    if after["planning_attempts"] == before["planning_attempts"] + 1:
        return False
    raise SmokeStop("PLANNING_ATTEMPT_COUNT_INVALID")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _run(_config(args), real=bool(args.real_retained_source))
    except SmokeStop as error:
        print(f"D8 STOP: {error}", file=sys.stderr)
        return 2
    except Exception:
        print("D8 STOP: CORE_STATE_UNAVAILABLE_OR_INVALID", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
