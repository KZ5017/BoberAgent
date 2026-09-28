"""Opt-in OFFLINE C1→C2→C3 validation of an existing retained acquisition.

No source fetch, extraction, execution, Node, transport, Knowledge or model calls.
Preflight uses SQLite read-only mode and never initializes Artifact storage.
The real mode writes inspection history (and applies existing Core migrations),
not source bytes. Conditional classification is discovered, never predetermined.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from boberagent_contracts import ArtifactRef, PoCAcquisitionRef
from boberagent_core.acquisitions import PoCAcquisition, PoCAcquisitionStatus
from boberagent_core.artifacts import (
    ArtifactStorageConfiguration,
    CoreArtifactService,
    FilesystemArtifactStorage,
)
from boberagent_core.inspections import (
    CorePoCInspectionService,
    CorePoCSupportClassificationService,
    CoverageStatus,
    InspectionStatus,
    PoCInspection,
    SemanticInspectionDocument,
    SourceCitation,
    SupportClassificationDocument,
)
from boberagent_core.inspections.classification_models import disposition, semantic_digest
from boberagent_core.inspections.models import InspectionDocument
from boberagent_core.inspections.semantic_models import SemanticItem
from boberagent_core.persistence import CoreDatabase, DatabaseConfig
from boberagent_core.persistence.migrations import upgrade_database


class SmokeStop(RuntimeError):
    """A bounded diagnostic, never exception/source text from an upstream parser."""


@dataclass(frozen=True)
class Selection:
    database_path: Path
    artifact_root: Path
    acquisition: PoCAcquisition


@dataclass(frozen=True)
class History:
    c1: PoCInspection
    c2: PoCInspection
    c3: PoCInspection


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check-config", action="store_true", help="metadata-only read-only preflight"
    )
    mode.add_argument(
        "--real-retained-source",
        action="store_true",
        help="authorize offline inspection-history writes",
    )
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--acquisition-ref", required=True, type=PoCAcquisitionRef)
    parser.add_argument("--expected-raw-artifact-ref", type=ArtifactRef)
    parser.add_argument("--expected-manifest-artifact-ref", type=ArtifactRef)
    parser.add_argument("--expected-raw-sha256")
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--expected-commit")
    return parser


def _readonly(path: Path) -> CoreDatabase:
    # URI escaping handles spaces, '?' and '#' in the operator-selected path.
    # mode=ro also prevents accidental repository writes, not just CLI writes.
    return CoreDatabase(DatabaseConfig(url=f"sqlite+pysqlite:///{path.as_uri()}?mode=ro&uri=true"))


def _preflight(args: argparse.Namespace) -> Selection:
    if not args.database.is_absolute() or not args.database.is_file():
        raise SmokeStop(
            "MISSING_DATABASE: --database must be an existing absolute Core SQLite file"
        )
    if not args.artifact_root.is_absolute() or not args.artifact_root.is_dir():
        raise SmokeStop(
            "MISSING_ARTIFACT_ROOT: --artifact-root must be an existing absolute directory"
        )
    database_path = args.database.resolve()
    artifact_root = args.artifact_root.resolve()
    database = _readonly(database_path)
    try:
        with database.unit_of_work() as work:
            acquisition = work.acquisitions.get(args.acquisition_ref)
            if acquisition is None:
                raise SmokeStop("ACQUISITION_NOT_FOUND")
            if (
                acquisition.status is not PoCAcquisitionStatus.COMPLETED
                or acquisition.receipt is None
            ):
                raise SmokeStop("ACQUISITION_NOT_COMPLETED")
            mission = work.missions.get(acquisition.mission_ref)
            hypothesis = work.research.get_hypothesis(acquisition.hypothesis_ref)
            candidate = work.research.get_candidate(acquisition.candidate_ref)
            if (
                mission is None
                or hypothesis is None
                or candidate is None
                or hypothesis.mission_ref != acquisition.mission_ref
                or candidate.mission_ref != acquisition.mission_ref
                or candidate.hypothesis_ref != acquisition.hypothesis_ref
            ):
                raise SmokeStop("ACQUISITION_OWNERSHIP_INVALID")
            receipt = acquisition.receipt
            for descriptor in (receipt.raw_source, receipt.manifest):
                record = work.artifacts.get_record(descriptor.artifact_id)
                if record is None or record.descriptor != descriptor:
                    raise SmokeStop("ACQUISITION_ARTIFACT_CATALOG_CONFLICT")
        expected = (
            (args.expected_raw_artifact_ref, receipt.raw_source.artifact_id, "RAW_ARTIFACT_REF"),
            (
                args.expected_manifest_artifact_ref,
                receipt.manifest.artifact_id,
                "MANIFEST_ARTIFACT_REF",
            ),
            (args.expected_raw_sha256, receipt.raw_archive_sha256, "RAW_SHA256"),
            (args.expected_manifest_sha256, receipt.manifest_sha256, "MANIFEST_SHA256"),
            (args.expected_commit, receipt.resolved_commit_sha, "COMMIT"),
        )
        for supplied, retained, label in expected:
            if supplied is not None and supplied != retained:
                raise SmokeStop(f"EXPECTED_{label}_MISMATCH")
        return Selection(database_path, artifact_root, acquisition)
    finally:
        database.dispose()


def _display(value: str) -> str:
    """Escape terminal controls and bound metadata; no source excerpts are printed."""
    bounded = value[:512] + ("[truncated]" if len(value) > 512 else "")
    return json.dumps(bounded, ensure_ascii=True)


def _name(value: str) -> str:
    # C2 names/flags are metadata, not commands, URLs, string defaults or environment values.
    return (
        _display(value) if re.fullmatch(r"[-A-Za-z_][A-Za-z0-9_.-]{0,127}", value) else "<REDACTED>"
    )


def _preview(selection: Selection) -> None:
    acquisition = selection.acquisition
    receipt = acquisition.receipt
    assert receipt is not None
    print(f"Database: {_display(str(selection.database_path))}")
    print(f"Artifact root: {_display(str(selection.artifact_root))}")
    print(f"MissionRef: {_display(str(acquisition.mission_ref))}")
    print(f"PoCCandidateRef: {_display(str(acquisition.candidate_ref))}")
    print(f"PoCAcquisitionRef: {_display(str(acquisition.acquisition_ref))}")
    print(f"Status: {acquisition.status.value}")
    print(f"Resolved commit: {receipt.resolved_commit_sha}")
    print(
        f"Raw Artifact: {_display(str(receipt.raw_source.artifact_id))} "
        f"sha256={receipt.raw_archive_sha256} size={receipt.raw_archive_size_bytes}"
    )
    print(
        f"Manifest Artifact: {_display(str(receipt.manifest.artifact_id))} sha256={receipt.manifest_sha256}"
    )
    print("Profiles: m20-c1-evidence@1 → m20-c2-deterministic@2 → m20-c3-support-classifier@2")
    print("OFFLINE ONLY; no fetch/extraction/execution/install/Secret/LLM/Knowledge/Node/MCP")


def _services(
    database: CoreDatabase, root: Path
) -> tuple[CoreArtifactService, CorePoCInspectionService]:
    artifacts = CoreArtifactService(
        database, FilesystemArtifactStorage(ArtifactStorageConfiguration(root=root))
    )
    return artifacts, CorePoCInspectionService(database, artifacts)


def _verify_retained_artifacts(artifacts: CoreArtifactService, acquisition: PoCAcquisition) -> None:
    """Rehash current bytes even when completed inspection history is reused.

    C1 still owns manifest/ZIP reconciliation; this checks cached evidence has not
    changed since that proof. Reads are streaming and bounded by the receipt.
    """
    receipt = acquisition.receipt
    assert receipt is not None
    for descriptor in (receipt.raw_source, receipt.manifest):
        digest = hashlib.sha256()
        size = 0
        with artifacts.open_content(descriptor.artifact_id) as stream:
            while chunk := stream.read(64 * 1024):
                size += len(chunk)
                if descriptor.size_bytes is None or size > descriptor.size_bytes:
                    raise SmokeStop("RETAINED_ARTIFACT_SIZE_MISMATCH")
                digest.update(chunk)
        if size != descriptor.size_bytes or digest.hexdigest() != descriptor.sha256:
            raise SmokeStop("RETAINED_ARTIFACT_INTEGRITY_MISMATCH")


def _pipeline(
    database: CoreDatabase, service: CorePoCInspectionService, selection: Selection
) -> History:
    acquisition = selection.acquisition
    # C1 verifies Artifact/manifest/ZIP identity; C2 independently verifies selected
    # entry bytes before semantic extraction. No manifest parser is duplicated here.
    c1_request = service.create(
        mission_ref=acquisition.mission_ref,
        hypothesis_ref=acquisition.hypothesis_ref,
        candidate_ref=acquisition.candidate_ref,
        acquisition_ref=acquisition.acquisition_ref,
    )
    c1 = service.inspect(c1_request.inspection_ref)
    if c1.status is not InspectionStatus.COMPLETED or not isinstance(
        c1.document, InspectionDocument
    ):
        raise SmokeStop("C1_NOT_COMPLETED")
    if not c1.document.manifest_validated or not c1.document.zip_reconciled:
        raise SmokeStop("C1_INTEGRITY_INCOMPLETE")
    c2_request = service.create_semantic(
        mission_ref=acquisition.mission_ref,
        hypothesis_ref=acquisition.hypothesis_ref,
        candidate_ref=acquisition.candidate_ref,
        acquisition_ref=acquisition.acquisition_ref,
    )
    c2 = service.inspect(c2_request.inspection_ref)
    if c2.status is not InspectionStatus.COMPLETED or not isinstance(
        c2.document, SemanticInspectionDocument
    ):
        raise SmokeStop("C2_NOT_COMPLETED")
    classifier = CorePoCSupportClassificationService(database)
    c3 = classifier.classify(classifier.create(c2.inspection_ref).inspection_ref)
    if c3.status is not InspectionStatus.COMPLETED or not isinstance(
        c3.document, SupportClassificationDocument
    ):
        raise SmokeStop("C3_NOT_COMPLETED")
    if (
        c3.document.semantic_inspection_ref != c2.inspection_ref
        or c3.document.semantic_document_sha256 != semantic_digest(c2.document)
    ):
        raise SmokeStop("C3_SEMANTIC_BINDING_INVALID")
    return History(c1, c2, c3)


def _locator(citation: SourceCitation) -> str:
    return (
        f"path={_display(citation.path)} bytes=[{citation.start},{citation.end}) "
        f"extractor={_display(citation.reader_id)}@{_display(citation.reader_version)}"
    )


def _item(item: SemanticItem) -> None:
    # Do not model_dump semantic items: names/defaults/source-derived strings need
    # deliberate presentation. Documentation OBSERVED means an observed claim only.
    authority = f"{item.origin.value}/{item.epistemic_state.value}"
    print(
        f"  id={item.item_id} path={_display(item.source_path)} authority={authority} reason={item.reason}"
    )
    for citation in item.citations:
        print(f"    citation: {_locator(citation)}")


def _summary(history: History, service: CorePoCInspectionService) -> None:
    c1, c2, c3 = history.c1, history.c2, history.c3
    assert isinstance(c1.document, InspectionDocument)
    semantic = c2.document
    classified = c3.document
    assert isinstance(semantic, SemanticInspectionDocument)
    assert isinstance(classified, SupportClassificationDocument)
    for attempt in (c1, c2, c3):
        print(
            f"Inspection: {attempt.inspection_ref} {attempt.profile_id}@{attempt.profile_version} {attempt.status.value}"
        )
    print(
        f"C1: manifest_validated={c1.document.manifest_validated} zip_reconciled={c1.document.zip_reconciled} "
        f"verified_entries={len(c1.document.verified_paths)} structural_unverified={len(c1.document.unverified_paths)}"
    )
    print(f"C2 document: {semantic.document_version} sha256={semantic_digest(semantic)}")
    for status in CoverageStatus:
        print(f"Coverage {status.value}: {sum(row.status is status for row in semantic.coverage)}")
    print(
        f"C2 verified entries: {len(semantic.verified_paths)}; unverified: {len(semantic.unverified_paths)}"
    )
    collections = (
        ("facts", semantic.facts),
        ("entrypoints", semantic.entrypoint_candidates),
        ("parameters", semantic.parameter_candidates),
        ("dependencies", semantic.dependency_observations),
        ("requirements", semantic.requirements),
        ("behaviors", semantic.behavior_indicators),
        ("risks", semantic.risk_indicators),
        ("unknowns", semantic.unknowns),
    )
    for name, items in collections:
        print(f"{name} count: {len(items)}")
    print(
        f"conflicts count: {len(semantic.conflicts)}; limit reasons: {','.join(_display(reason) for reason in semantic.limit_reasons) or 'none'}"
    )
    print("File coverage:")
    for row in semantic.coverage:
        print(
            f"  {_display(row.path)} {row.status.value} {_display(row.extractor_id)}@{row.extractor_version} {row.reason}"
        )
    print("Entrypoint candidates (NOT commands or selected entrypoints):")
    for item in semantic.entrypoint_candidates:
        _item(item)
        for citation in item.citations:
            print(f"    derived lines: {service.citation_lines(c2.inspection_ref, citation)}")
        print(
            f"    runtime={item.runtime} style={item.invocation_style} parameter_refs={','.join(item.parameter_candidate_refs) or 'none'}"
        )
    print("Parameter candidates (NOT resolved bindings):")
    for parameter in semantic.parameter_candidates:
        _item(parameter)
        default = (
            "<REDACTED>" if parameter.default_redacted else json.dumps(parameter.default_literal)
        )
        print(
            f"    name={_name(parameter.name)} role={parameter.role.value} required={parameter.required} default={default}"
        )
    print("Dependencies (NOT installation instructions):")
    for dependency in semantic.dependency_observations:
        _item(dependency)
        print(f"    type={dependency.kind.value} name={_name(dependency.name)}")
    for label, indicators in (
        ("Requirements", semantic.requirements),
        ("Behaviors", semantic.behavior_indicators),
        ("Risks", semantic.risk_indicators),
    ):
        print(label + ":")
        for indicator in indicators:
            _item(indicator)
            print(f"    code={indicator.kind.value}")
    print("Unknowns (materiality comes only from C3 reason/coverage refs):")
    for unknown in semantic.unknowns:
        _item(unknown)
    print("Conflicts (neither claim wins):")
    for conflict in semantic.conflicts:
        print(
            f"  id={conflict.conflict_id} kind={conflict.kind} item_refs={','.join(conflict.item_refs)}"
        )
        for citation in conflict.citations:
            print(f"    citation: {_locator(citation)}")
    print(
        f"C3 classification: {classified.classification.value} (conditional support, NOT authorization or safety)"
    )
    print(
        f"C3 document: {classified.document_version}; parent={classified.semantic_inspection_ref}; digest={classified.semantic_document_sha256}"
    )
    by_id = {item.item_id: item for _, items in collections for item in items}
    for reason in classified.reasons:
        print(f"Reason: {reason.code.value} [{disposition(reason.code).value}]")
        for ref in reason.item_refs:
            _item(by_id[ref])
        for ref in reason.conflict_refs:
            print(f"  conflict_ref={ref}")
        for path in reason.coverage_paths:
            print(f"  coverage_path={_display(path)}")
    print(f"Blocking unknowns: {','.join(classified.blocking_unknown_refs) or 'none'}")
    print(f"Assistance unknowns: {','.join(classified.assistance_unknown_refs) or 'none'}")
    print(f"Blocking conflicts: {','.join(classified.blocking_conflict_refs) or 'none'}")


def _spot_checks(service: CorePoCInspectionService, c2: PoCInspection) -> None:
    assert isinstance(c2.document, SemanticInspectionDocument)
    # One citation per extractor, in stable order, maximum five. No raw excerpts:
    # display only exact-span hash/length + derived line location.
    chosen: dict[str, SourceCitation] = {}
    priority = ("python-ast", "powershell-lexical", "shell-lexical", "documentation-claims")
    for citation in sorted(
        c2.document.citations,
        key=lambda c: (
            priority.index(c.reader_id) if c.reader_id in priority else len(priority),
            c.reader_id,
            c.path,
            c.start,
            c.end,
        ),
    ):
        if citation.reader_id not in chosen and len(chosen) < 5:
            chosen[citation.reader_id] = citation
    for citation in chosen.values():
        service.validate_citation(c2.inspection_ref, citation)
        content = service.read_citation(c2.inspection_ref, citation)
        lines = service.citation_lines(c2.inspection_ref, citation)
        print(
            f"Citation spot check: {_locator(citation)} lines={lines} "
            f"length={len(content)} span_sha256={hashlib.sha256(content).hexdigest()}"
        )
    print(f"Citation spot checks verified: {len(chosen)} (no excerpts)")


def _run(args: argparse.Namespace) -> History | None:
    selection = _preflight(args)
    _preview(selection)
    if args.check_config:
        print("OFFLINE RETAINED-SOURCE CONFIGURATION VALID; no database writes or source reads")
        return None
    if not args.real_retained_source:
        raise SmokeStop("REAL_RETAINED_SOURCE_OPT_IN_REQUIRED")
    database = CoreDatabase(DatabaseConfig.sqlite(selection.database_path))
    try:
        upgrade_database(database)  # Explicit opt-in only; no new C4 migration.
        artifacts, service = _services(database, selection.artifact_root)
        _verify_retained_artifacts(artifacts, selection.acquisition)
        history = _pipeline(database, service, selection)
        _summary(history, service)
        _spot_checks(service, history.c2)
        before = service.list_for_acquisition(selection.acquisition.acquisition_ref)
    finally:
        database.dispose()
    # First verify immutable rows using read-only metadata; then exercise the real
    # create/reuse APIs and assert no extra history appears on a second invocation.
    reopened_selection = _preflight(args)
    if reopened_selection != selection:
        raise SmokeStop("ACQUISITION_CHANGED_AFTER_REOPEN")
    reopened = CoreDatabase(DatabaseConfig.sqlite(selection.database_path))
    try:
        artifacts, service = _services(reopened, selection.artifact_root)
        for attempt in (history.c1, history.c2, history.c3):
            if service.get(attempt.inspection_ref) != attempt:
                raise SmokeStop("INSPECTION_CHANGED_AFTER_REOPEN")
        receipt = selection.acquisition.receipt
        assert receipt is not None
        if not all(
            artifacts.content_available(d.artifact_id)
            for d in (receipt.raw_source, receipt.manifest)
        ):
            raise SmokeStop("ARTIFACT_UNAVAILABLE_AFTER_REOPEN")
        if _pipeline(reopened, service, selection) != history:
            raise SmokeStop("INSPECTION_REUSE_FAILED")
        if service.list_for_acquisition(selection.acquisition.acquisition_ref) != before:
            raise SmokeStop("INSPECTION_HISTORY_CHANGED_ON_REUSE")
        print(
            "PASS: acquisition/C1/C2/C3 unchanged after Core reopen; identical invocation reused history"
        )
        print("STOP: no ExecutionPlan, binding, staging, authorization, preparation or execution")
        return history
    finally:
        reopened.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _run(args)
    except SmokeStop as error:
        print(f"C4 STOP: {error}", file=sys.stderr)
        return 2
    except Exception:
        # Database validation/parser errors can include source strings or operator
        # paths. Never print arbitrary exception text or a traceback here.
        print(
            "C4 STOP: CORE_STATE_OR_INSPECTION_UNAVAILABLE; retained state must be valid and accessible",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
