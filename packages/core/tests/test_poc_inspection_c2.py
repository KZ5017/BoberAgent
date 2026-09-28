"""Offline C2 profile: migration-backed exact evidence, deterministic facts and reopen."""

from __future__ import annotations

from pathlib import Path

import pytest
from boberagent_core import (
    ArtifactStorageConfiguration,
    CoreArtifactService,
    CoreDatabase,
    FilesystemArtifactStorage,
)
from boberagent_core.inspections import (
    CorePoCInspectionService,
    CoverageStatus,
    InspectionStatus,
    PoCInspection,
    SemanticInspectionDocument,
    SemanticInspectionLimits,
    SourceOrigin,
)
from boberagent_core.inspections.semantic_models import (
    BehaviorKind,
    DependencyKind,
    EpistemicState,
    ImportKind,
    ParameterRole,
    RequirementKind,
    RiskKind,
)
from test_core_poc_acquisition import _bounds
from test_poc_inspection_c1 import _setup

FIXTURES = Path(__file__).parent / "fixtures/inspection_c2"


def fixture_repository() -> dict[str, bytes]:
    names = ("poc.py", "helper.ps1", "run.sh", "pyproject.toml", "requirements.txt")
    files = {name: (FIXTURES / (name + ".source")).read_bytes() for name in names}
    files["README.md"] = (FIXTURES / "README.md").read_bytes()
    files["image.png"] = b"\x89PNG\x00\xff"
    return files


def prepare(
    database: CoreDatabase,
    tmp_path: Path,
    files: dict[str, bytes],
    limits: SemanticInspectionLimits | None = None,
) -> tuple[CorePoCInspectionService, PoCInspection]:
    bounds = _bounds().model_copy(
        update={
            "max_download_bytes": 4 * 1024 * 1024,
            "max_uncompressed_bytes": 8 * 1024 * 1024,
            "max_single_file_bytes": 4 * 1024 * 1024,
            "max_file_count": 1000,
            "max_compression_ratio": 10_000,
        }
    )
    service, c1, _ = _setup(database, tmp_path, files=files, bounds=bounds)
    c2 = service.create_semantic(
        mission_ref=c1.mission_ref,
        hypothesis_ref=c1.hypothesis_ref,
        candidate_ref=c1.candidate_ref,
        acquisition_ref=c1.acquisition_ref,
        limits=limits,
    )
    return service, c2


def completed_document(
    service: CorePoCInspectionService, requested: PoCInspection
) -> tuple[PoCInspection, SemanticInspectionDocument]:
    completed = service.inspect(requested.inspection_ref)
    assert completed.status is InspectionStatus.COMPLETED, completed.diagnostic
    assert isinstance(completed.document, SemanticInspectionDocument)
    return completed, completed.document


def test_offline_semantic_profile_reopen(
    database: CoreDatabase, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service, requested = prepare(database, tmp_path, fixture_repository())
    completed, document = completed_document(service, requested)
    assert completed.profile_id == "m20-c2-deterministic"
    assert completed.profile_version == "1"
    assert document.document_version == "m20-c2-deterministic-v1"
    assert {entry.runtime for entry in document.entrypoint_candidates} == {"python", "shell"}
    assert {parameter.role for parameter in document.parameter_candidates} >= {
        ParameterRole.TARGET_HOST,
        ParameterRole.TARGET_PORT,
        ParameterRole.CREDENTIAL,
        ParameterRole.UNKNOWN,
    }
    assert {item.kind for item in document.behavior_indicators} >= {
        BehaviorKind.NETWORK_CONNECT,
        BehaviorKind.NETWORK_BIND_LISTEN,
        BehaviorKind.SUBPROCESS_EXECUTION,
        BehaviorKind.FILE_WRITE,
        BehaviorKind.ENVIRONMENT_ACCESS,
    }
    assert {conflict.kind for conflict in document.conflicts} == {
        "RUNTIME_CLAIMS_DIFFER",
        "CREDENTIAL_CLAIMS_DIFFER",
    }
    assert service.inspect(completed.inspection_ref) == completed
    assert (
        service.create_semantic(
            mission_ref=completed.mission_ref,
            hypothesis_ref=completed.hypothesis_ref,
            candidate_ref=completed.candidate_ref,
            acquisition_ref=completed.acquisition_ref,
        )
        == completed
    )
    files = fixture_repository()
    for citation in document.citations:
        assert (
            service.read_citation(completed.inspection_ref, citation)
            == files[citation.path][citation.start : citation.end]
        )
    with database.unit_of_work() as work:
        assert work.inspections.get(completed.inspection_ref) == completed
    database.dispose()
    again_db = CoreDatabase(database.config)
    try:
        again = CorePoCInspectionService(
            again_db,
            CoreArtifactService(
                again_db,
                FilesystemArtifactStorage(
                    ArtifactStorageConfiguration(root=tmp_path / "artifacts")
                ),
            ),
        )
        assert again.get(completed.inspection_ref) == completed
        assert again.read_citation(completed.inspection_ref, document.citations[0])
    finally:
        again_db.dispose()
    print(
        f"inspection={completed.inspection_ref} profile={completed.profile_id}@{completed.profile_version} status={completed.status}"
    )
    print(
        f"files={len(document.coverage)} verified={len(document.verified_paths)} facts={len(document.facts)} unknowns={len(document.unknowns)} conflicts={len(document.conflicts)}"
    )
    print("roles=" + ",".join(sorted({item.role.value for item in document.parameter_candidates})))
    print(
        "behaviors=" + ",".join(sorted({item.kind.value for item in document.behavior_indicators}))
    )
    output = capsys.readouterr().out
    assert "synthetic-do-not-copy" not in output
    print(output, end="")


def test_python_facts_and_exact_citations(database: CoreDatabase, tmp_path: Path) -> None:
    files = {"poc.py": fixture_repository()["poc.py"]}
    service, requested = prepare(database, tmp_path, files)
    completed, document = completed_document(service, requested)
    parameters = {item.name: item for item in document.parameter_candidates}
    assert parameters["--target"].required is True
    assert parameters["--port"].default_literal == 80
    assert parameters["--password"].default_redacted
    assert "synthetic-do-not-copy" not in document.model_dump_json()
    imports = {item.name: item for item in document.dependency_observations}
    assert imports["os"].import_kind is ImportKind.STDLIB_LOOKING
    assert imports["requests"].import_kind is ImportKind.THIRD_PARTY_LOOKING
    assert all(item.kind is DependencyKind.IMPORTED_MODULE for item in imports.values())
    assert document.entrypoint_candidates[0].parameter_candidate_refs
    for indicator in document.behavior_indicators:
        cited = service.read_citation(completed.inspection_ref, indicator.citations[0])
        assert cited in {
            b"requests.get",
            b"connection.connect",
            b"connection.bind",
            b"connection.listen",
            b"socket.gethostbyname",
            b"subprocess.run",
            b"os.getenv",
            b"os.environ",
            b"os.geteuid",
            b"open",
            b'Path("data").write_text',
            b"os.unlink",
        }
    assert RiskKind.ARBITRARY_COMMAND_EXECUTION in {item.kind for item in document.risk_indicators}
    assert all(item.epistemic_state is EpistemicState.OBSERVED for item in document.facts)


@pytest.mark.parametrize("path", ["helper.ps1", "run.sh"])
def test_lexical_parameters_and_citations(
    database: CoreDatabase, tmp_path: Path, path: str
) -> None:
    service, requested = prepare(database, tmp_path, {path: fixture_repository()[path]})
    completed, document = completed_document(service, requested)
    assert document.coverage[0].status is CoverageStatus.PARTIAL
    assert document.parameter_candidates
    assert {item.kind for item in document.behavior_indicators} >= {
        BehaviorKind.NETWORK_CONNECT,
        BehaviorKind.FILE_WRITE,
    }
    assert not document.risk_indicators  # comment-only tokens are masked
    for item in (*document.behavior_indicators, *document.parameter_candidates):
        assert service.read_citation(completed.inspection_ref, item.citations[0])
    if path.endswith(".ps1"):
        assert [item.name for item in document.parameter_candidates] == ["$Target", "$Port"]
        assert (
            service.read_citation(
                completed.inspection_ref, document.behavior_indicators[0].citations[0]
            )
            == b"Invoke-WebRequest"
        )
    else:
        assert {item.name for item in document.parameter_candidates} >= {"$1", "-t", "-p"}


def test_declarative_and_documentation_authority(database: CoreDatabase, tmp_path: Path) -> None:
    files = fixture_repository()
    service, requested = prepare(
        database,
        tmp_path,
        {
            name: data
            for name, data in files.items()
            if name in {"README.md", "pyproject.toml", "requirements.txt", "poc.py"}
        },
    )
    completed, document = completed_document(service, requested)
    dependencies = [
        item
        for item in document.dependency_observations
        if item.kind is DependencyKind.DECLARED_PACKAGE
    ]
    assert {item.name for item in dependencies} == {"requests", "aiohttp"}
    for item in dependencies:
        assert item.origin is SourceOrigin.DECLARATIVE_METADATA
        assert item.name.encode() in service.read_citation(
            completed.inspection_ref, item.citations[0]
        )
    assert any(item.reason == "UNSUPPORTED_REQUIREMENT_SYNTAX" for item in document.unknowns)
    runtime = [item for item in document.requirements if item.kind is RequirementKind.RUNTIME]
    assert {(item.name, item.origin) for item in runtime} == {
        ("3.8", SourceOrigin.DOCUMENTATION),
        (">=3.11", SourceOrigin.DECLARATIVE_METADATA),
    }
    assert len(document.conflicts) == 2
    assert all(
        item.origin is SourceOrigin.DOCUMENTATION
        for item in document.facts
        if item.kind.startswith("DOCUMENTED")
    )


@pytest.mark.parametrize(
    ("content", "status"),
    [
        (b"\x00\xff", CoverageStatus.SKIPPED_BINARY),
        (b"\xff\xff", CoverageStatus.SKIPPED_ENCODING),
        (b"def broken(:", CoverageStatus.PARSER_FAILED),
    ],
)
def test_semantic_failure_is_coverage(
    database: CoreDatabase, tmp_path: Path, content: bytes, status: CoverageStatus
) -> None:
    service, requested = prepare(
        database,
        tmp_path,
        {"poc.py": content, "sound.py": b'import os\nif __name__ == "__main__": pass\n'},
    )
    _, document = completed_document(service, requested)
    assert {entry.path: entry.status for entry in document.coverage}["poc.py"] is status
    assert any(item.source_path == "poc.py" for item in document.unknowns)
    assert any(item.source_path == "sound.py" for item in document.facts)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16-le", "utf-16-be"])
def test_unicode_bom_crlf_precise_ast_offsets(
    database: CoreDatabase, tmp_path: Path, encoding: str
) -> None:
    text = 'import os\r\nlabel = "é😀"; os.getenv("X")\r\n'
    content = text.encode(encoding)
    if encoding.startswith("utf-16"):
        content = (b"\xff\xfe" if encoding.endswith("le") else b"\xfe\xff") + content
    service, requested = prepare(database, tmp_path, {"poc.py": content})
    completed, document = completed_document(service, requested)
    indicator = next(
        item
        for item in document.behavior_indicators
        if item.kind is BehaviorKind.ENVIRONMENT_ACCESS
    )
    citation = indicator.citations[0]
    codec = encoding.replace("utf-8-sig", "utf-8")
    assert service.read_citation(completed.inspection_ref, citation) == "os.getenv".encode(codec)
    assert service.citation_lines(completed.inspection_ref, citation) == (2, 2)
