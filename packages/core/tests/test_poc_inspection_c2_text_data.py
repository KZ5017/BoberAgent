"""Narrow decoding and declarative source-locator edge cases."""

from pathlib import Path

from boberagent_core import CoreDatabase
from boberagent_core.inspections import CoverageStatus, InspectionStatus
from test_poc_inspection_c2 import completed_document, prepare


def test_lone_cr_is_explicit_unsupported_text(database: CoreDatabase, tmp_path: Path) -> None:
    service, requested = prepare(database, tmp_path, {"poc.py": b"import os\rimport sys\r"})
    _, document = completed_document(service, requested)
    assert document.coverage[0].status is CoverageStatus.SKIPPED_ENCODING
    assert document.coverage[0].reason == "UNSUPPORTED_NEWLINES"
    assert not document.facts


def test_metadata_comment_is_not_dependency_evidence(
    database: CoreDatabase, tmp_path: Path
) -> None:
    content = b"""[project]
dependencies = [
    # "requests>=2.31" is an unrelated comment.
    "requests>=2.31",
]
"""
    service, requested = prepare(database, tmp_path, {"pyproject.toml": content})
    completed, document = completed_document(service, requested)
    dependency = document.dependency_observations[0]
    citation = dependency.citations[0]
    assert service.read_citation(completed.inspection_ref, citation) == b"requests>=2.31"
    assert service.citation_lines(completed.inspection_ref, citation) == (4, 4)


def test_complex_toml_location_is_not_guessed(database: CoreDatabase, tmp_path: Path) -> None:
    content = b'[project]\nrequires-python = ">=3.11"\ndescription = """multi\nline"""\n'
    service, requested = prepare(database, tmp_path, {"pyproject.toml": content})
    _, document = completed_document(service, requested)
    assert any(item.reason == "UNSUPPORTED_METADATA_LOCATION" for item in document.unknowns)
    assert not document.requirements


def test_missing_selected_path_is_config_failure(database: CoreDatabase, tmp_path: Path) -> None:
    service, requested = prepare(database, tmp_path, {"poc.py": b"import os\n"})
    restricted = service.create_semantic(
        mission_ref=requested.mission_ref,
        hypothesis_ref=requested.hypothesis_ref,
        candidate_ref=requested.candidate_ref,
        acquisition_ref=requested.acquisition_ref,
        selected_paths=("missing.py",),
    )
    failed = service.inspect(restricted.inspection_ref)
    assert failed.status is InspectionStatus.FAILED
    assert failed.diagnostic == "INSPECTION_CONFIG_INVALID"
