"""Additional exact-span, selection, restart and conservative-syntax regressions."""

from pathlib import Path

import pytest
from boberagent_core import CoreDatabase
from boberagent_core.inspections import InspectionError, InspectionStatus, SourceOrigin
from boberagent_core.inspections.semantic_models import BehaviorKind, ImportKind
from test_core_poc_acquisition import NOW
from test_poc_inspection_c2 import completed_document, prepare


def test_definitions_imports_parameters_and_guards_cite_actual_syntax(
    database: CoreDatabase, tmp_path: Path
) -> None:
    content = b"""import argparse as ap
from .helper import value
import unresolved_package
import sys
parser = ap.ArgumentParser()
parser.add_argument("--port", default=42)
class LocalClass:
    pass
async def work():
    pass
def main():
    sys.argv[1]
if __name__ == "__main__":
    main()
"""
    service, requested = prepare(
        database, tmp_path, {"poc.py": content, "helper.py": b"value = 1\n"}
    )
    completed, document = completed_document(service, requested)
    expected = {
        "ASYNC_FUNCTION": b"async def work():",
        "FUNCTION": b"def main():",
        "CLASS": b"class LocalClass:",
        "MAIN_GUARD": b'__name__ == "__main__"',
        "ARGPARSE": b"ap.ArgumentParser",
        "ARGV": b"sys.argv",
    }
    for item in document.facts:
        if item.source_path == "poc.py" and item.kind in expected:
            assert (
                service.read_citation(completed.inspection_ref, item.citations[0])
                == expected[item.kind]
            )
    imports = {item.name: item for item in document.dependency_observations}
    assert imports["helper"].import_kind is ImportKind.LOCAL_RELATIVE
    assert imports["unresolved_package"].import_kind is ImportKind.UNKNOWN
    assert (
        service.read_citation(completed.inspection_ref, imports["helper"].citations[0])
        == b"from .helper import value"
    )
    parameter = document.parameter_candidates[0]
    assert (
        service.read_citation(completed.inspection_ref, parameter.citations[0])
        == b'parser.add_argument("--port", default=42)'
    )
    assert parameter.default_literal == 42
    assert any(item.reason == "DYNAMIC_PARAMETER_VALUES" for item in document.unknowns)


def test_quoted_commands_are_data_and_ps_defaults_not_parameters(
    database: CoreDatabase, tmp_path: Path
) -> None:
    files = {
        "run.sh": b"echo \"curl rm sudo\"\necho 'nc'\n",
        "helper.ps1": b'param([string]$Target = $env:TARGET, [int]$Port = 80)\nWrite-Output "Invoke-Expression Start-Process"\nInvoke-WebRequest $Target\n',
    }
    service, requested = prepare(database, tmp_path, files)
    completed, document = completed_document(service, requested)
    assert {item.name for item in document.parameter_candidates} == {"$Target", "$Port"}
    assert {item.kind for item in document.behavior_indicators} == {BehaviorKind.NETWORK_CONNECT}
    assert not document.risk_indicators
    assert (
        service.read_citation(
            completed.inspection_ref, document.behavior_indicators[0].citations[0]
        )
        == b"Invoke-WebRequest"
    )


def test_numeric_credential_defaults_redacted(database: CoreDatabase, tmp_path: Path) -> None:
    service, requested = prepare(
        database,
        tmp_path,
        {
            "poc.py": b'import argparse\np=argparse.ArgumentParser()\np.add_argument("--password", default=987654321)\n'
        },
    )
    _, document = completed_document(service, requested)
    parameter = document.parameter_candidates[0]
    assert parameter.default_literal is None
    assert parameter.default_redacted
    assert "987654321" not in document.model_dump_json()


def test_explicit_selection_and_recovery_preserve_profile(
    database: CoreDatabase, tmp_path: Path
) -> None:
    service, requested = prepare(
        database, tmp_path, {"a.py": b"import os\n", "b.py": b"import sys\n"}
    )
    restricted = service.create_semantic(
        mission_ref=requested.mission_ref,
        hypothesis_ref=requested.hypothesis_ref,
        candidate_ref=requested.candidate_ref,
        acquisition_ref=requested.acquisition_ref,
        selected_paths=("a.py",),
    )
    assert restricted.config_fingerprint != requested.config_fingerprint
    with database.unit_of_work() as work:
        work.inspections.update(
            restricted.model_copy(update={"status": InspectionStatus.INSPECTING, "started_at": NOW})
        )
    database.dispose()
    assert service.recover_interrupted()[0].status is InspectionStatus.INTERRUPTED
    assert service.recover_interrupted() == ()
    again = service.create_semantic(
        mission_ref=requested.mission_ref,
        hypothesis_ref=requested.hypothesis_ref,
        candidate_ref=requested.candidate_ref,
        acquisition_ref=requested.acquisition_ref,
        selected_paths=("a.py",),
    )
    assert again.inspection_ref != restricted.inspection_ref
    _, document = completed_document(service, again)
    assert document.verified_paths == ("a.py",)
    assert (
        next(item.reason for item in document.coverage if item.path == "b.py")
        == "NOT_SELECTED_BY_PROFILE_CONFIG"
    )
    assert all(item.origin is SourceOrigin.CODE for item in document.facts)


def test_c2_still_fails_manifest_entry_hash_mismatch(
    database: CoreDatabase, tmp_path: Path
) -> None:
    from test_poc_inspection_c1 import _manifest, _setup, _zip

    files = {"source.py": b"import os\n"}
    raw = _zip(files)
    manifest = _manifest(raw, files)
    entries = manifest["entries"]
    assert isinstance(entries, list)
    entries[0]["sha256"] = "f" * 64
    service, c1, _ = _setup(database, tmp_path, raw=raw, files=files, manifest_change=manifest)
    c2 = service.create_semantic(
        mission_ref=c1.mission_ref,
        hypothesis_ref=c1.hypothesis_ref,
        candidate_ref=c1.candidate_ref,
        acquisition_ref=c1.acquisition_ref,
    )
    failed = service.inspect(c2.inspection_ref)
    assert failed.status is InspectionStatus.FAILED
    assert failed.diagnostic == "ENTRY_HASH_MISMATCH"
    with pytest.raises(InspectionError, match="NOT_REQUESTED"):
        service.inspect(c2.inspection_ref)
