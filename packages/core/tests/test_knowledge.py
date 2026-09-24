"""Local deterministic M17 Knowledge and Procedure behavior."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
from boberagent_core import WorkflowDefinition, WorkflowStepDefinition
from boberagent_core.knowledge import (
    CuratedMarkdownLoader,
    KnowledgeConflict,
    KnowledgeId,
    KnowledgeRepository,
    KnowledgeRequest,
    KnowledgeRoute,
    KnowledgeRouter,
    KnowledgeSourceError,
    KnowledgeStatus,
    ProcedureId,
    ProcedureRegistry,
    UnsupportedKnowledgeRoute,
)
from pydantic import ValidationError

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "knowledge"
REFERENCE_NAME = "network-service-evidence.md"
PROCEDURE_NAME = "network-service-discovery.md"


def _sources(tmp_path: Path) -> Path:
    root = tmp_path / "curated"
    (root / "reference").mkdir(parents=True)
    (root / "procedures").mkdir()
    shutil.copyfile(SOURCE_ROOT / "reference" / REFERENCE_NAME, root / "reference" / REFERENCE_NAME)
    shutil.copyfile(
        SOURCE_ROOT / "procedures" / PROCEDURE_NAME, root / "procedures" / PROCEDURE_NAME
    )
    return root


def _router(root: Path) -> KnowledgeRouter:
    return KnowledgeRouter.from_directory(
        root, known_capability_ids=frozenset({"network.service_discovery"})
    )


def test_curated_source_to_router_preserves_exact_identity_structure_and_provenance(
    tmp_path: Path,
) -> None:
    root = _sources(tmp_path)
    router = _router(root)
    document = router.get_canonical(KnowledgeId("knowledge.network.service_evidence"))
    procedure = router.lookup_procedure(ProcedureId("procedure.network.service_discovery"))
    assert document is not None and procedure is not None
    assert document.status is KnowledgeStatus.CANONICAL
    assert document.provenance.source_path == f"reference/{REFERENCE_NAME}"
    assert (
        document.provenance.content_sha256
        == hashlib.sha256((root / "reference" / REFERENCE_NAME).read_bytes()).hexdigest()
    )
    assert document.headings[1].path == ("Service discovery evidence", "Interpretation")
    assert "Mission fact" in document.body
    assert procedure.candidate_capability_ids == ("network.service_discovery",)
    assert procedure.steps[0].operation == "discover"
    assert procedure.related_knowledge_ids == (document.knowledge_id,)

    # This is a description of operational intent. Only Workflow owns execution and inputs.
    workflow = WorkflowDefinition(
        definition_id=str(procedure.procedure_id),
        version=str(procedure.version),
        steps=(
            WorkflowStepDefinition(
                step_id=procedure.steps[0].step_id,
                capability_id=procedure.steps[0].capability_id,
                operation=procedure.steps[0].operation,
                inputs={"asset_ref": "asset-supplied-by-mission"},
            ),
        ),
    )
    assert workflow.procedure_ref == "procedure.network.service_discovery@1"


def test_relocation_changes_provenance_not_identity_or_content_hash(tmp_path: Path) -> None:
    root = _sources(tmp_path)
    first = _router(root)
    original = first.get_canonical(KnowledgeId("knowledge.network.service_evidence"))
    assert original is not None
    (root / "reference" / REFERENCE_NAME).rename(root / "reference" / "renamed.md")
    second = first.reload()
    relocated = second.get_canonical(original.knowledge_id)
    assert relocated is not None
    assert relocated.knowledge_id == original.knowledge_id
    assert relocated.provenance.content_sha256 == original.provenance.content_sha256
    assert relocated.provenance.source_path == "reference/renamed.md"
    assert original.provenance.source_path == f"reference/{REFERENCE_NAME}"
    assert second.reload().resolve(KnowledgeRequest(knowledge_id=original.knowledge_id)) == (
        second.resolve(KnowledgeRequest(knowledge_id=original.knowledge_id))
    )


def test_canonical_and_explicit_historical_versions(tmp_path: Path) -> None:
    root = _sources(tmp_path)
    reference = root / "reference" / REFERENCE_NAME
    old = reference.read_text(encoding="utf-8").replace(
        'status = "CANONICAL"', 'status = "DEPRECATED"'
    )
    reference.write_text(old, encoding="utf-8")
    (root / "reference" / "current.md").write_text(
        old.replace("version = 1", "version = 2").replace(
            'status = "DEPRECATED"', 'status = "CANONICAL"'
        ),
        encoding="utf-8",
    )
    procedure = root / "procedures" / PROCEDURE_NAME
    previous = procedure.read_text(encoding="utf-8").replace(
        'status = "CANONICAL"', 'status = "DEPRECATED"'
    )
    procedure.write_text(previous, encoding="utf-8")
    (root / "procedures" / "current.md").write_text(
        previous.replace("version = 1", "version = 2").replace(
            'status = "DEPRECATED"', 'status = "CANONICAL"'
        ),
        encoding="utf-8",
    )
    router = _router(root)
    knowledge_id = KnowledgeId("knowledge.network.service_evidence")
    procedure_id = ProcedureId("procedure.network.service_discovery")
    current_document = router.get_canonical(knowledge_id)
    previous_document = router.repository.get(knowledge_id, version=1)
    current_procedure = router.lookup_procedure(procedure_id)
    previous_procedure = router.lookup_procedure(procedure_id, version=1)
    assert current_document is not None and current_document.version == 2
    assert previous_document is not None
    assert previous_document.status is KnowledgeStatus.DEPRECATED
    assert current_procedure is not None and current_procedure.version == 2
    assert previous_procedure is not None
    assert previous_procedure.status is KnowledgeStatus.DEPRECATED
    assert len(router.repository.list_documents()) == 1
    assert len(router.repository.list_documents(status=None)) == 2
    assert (
        router.resolve(KnowledgeRequest(knowledge_id=knowledge_id, version=1)).documents[0].status
        is KnowledgeStatus.DEPRECATED
    )


@pytest.mark.parametrize(
    ("replacement", "expected"),
    [
        (('id = "knowledge.network.service_evidence"', ""), "invalid curated source"),
        (("version = 1", "version = 0"), "greater than 0"),
        (('status = "CANONICAL"', 'status = "INVALID"'), "invalid curated source"),
        (('type = "reference"', "type = [broken"), "invalid curated source"),
        (
            ('source_kind = "author_maintained"', 'source_kind = "mission_observation"'),
            "invalid curated source",
        ),
        (
            (
                'source_kind = "author_maintained"',
                'source_kind = "author_maintained"\nsecret_ref = "secret-leak"',
            ),
            "Mission/Secret metadata",
        ),
    ],
)
def test_malformed_reference_rejected(
    tmp_path: Path, replacement: tuple[str, str], expected: str
) -> None:
    root = _sources(tmp_path)
    path = root / "reference" / REFERENCE_NAME
    path.write_text(path.read_text(encoding="utf-8").replace(*replacement), encoding="utf-8")
    with pytest.raises(KnowledgeSourceError, match=expected):
        _router(root)


def test_missing_front_matter_and_symlink_escape_rejected(tmp_path: Path) -> None:
    root = _sources(tmp_path)
    loader = CuratedMarkdownLoader(root)
    source = root / "reference" / REFERENCE_NAME
    source.write_text("# Uncurated Mission output", encoding="utf-8")
    with pytest.raises(KnowledgeSourceError, match="front matter"):
        loader.load_reference(source)
    outside = tmp_path / "outside.md"
    outside.write_text("not curated", encoding="utf-8")
    link = root / "reference" / "outside-link.md"
    link.symlink_to(outside)
    with pytest.raises(KnowledgeSourceError, match="not a regular file"):
        loader.load_reference(link)
    mission_dir = root / "mission-artifacts"
    mission_dir.mkdir()
    mission_file = mission_dir / "misplaced.md"
    shutil.copyfile(SOURCE_ROOT / "reference" / REFERENCE_NAME, mission_file)
    with pytest.raises(KnowledgeSourceError, match="unsupported curated source directory"):
        loader.files("mission-artifacts")
    with pytest.raises(KnowledgeSourceError, match="not a regular file"):
        loader.load_reference(mission_file)


def test_duplicate_identity_and_canonical_conflicts_rejected(tmp_path: Path) -> None:
    root = _sources(tmp_path)
    original = (root / "reference" / REFERENCE_NAME).read_text(encoding="utf-8")
    duplicate = root / "reference" / "duplicate.md"
    duplicate.write_text(original, encoding="utf-8")
    with pytest.raises(KnowledgeConflict, match="duplicate Knowledge"):
        _router(root)
    duplicate.write_text(original.replace("version = 1", "version = 2"), encoding="utf-8")
    with pytest.raises(KnowledgeConflict, match="multiple current canonical"):
        _router(root)

    duplicate.unlink()
    procedure = (root / "procedures" / PROCEDURE_NAME).read_text(encoding="utf-8")
    duplicate_procedure = root / "procedures" / "duplicate.md"
    duplicate_procedure.write_text(procedure, encoding="utf-8")
    with pytest.raises(KnowledgeConflict, match="duplicate Procedure"):
        _router(root)
    duplicate_procedure.write_text(
        procedure.replace("version = 1", "version = 2"), encoding="utf-8"
    )
    with pytest.raises(KnowledgeConflict, match="multiple current canonical Procedure"):
        _router(root)


def test_invalid_procedure_capability_or_cross_reference_rejected(tmp_path: Path) -> None:
    root = _sources(tmp_path)
    with pytest.raises(KnowledgeConflict, match="unknown Capabilities"):
        KnowledgeRouter.from_directory(root, known_capability_ids=frozenset())
    reference = root / "reference" / REFERENCE_NAME
    reference.write_text(
        reference.read_text(encoding="utf-8").replace(
            'procedure_ids = ["procedure.network.service_discovery"]',
            'procedure_ids = ["procedure.missing"]',
        ),
        encoding="utf-8",
    )
    with pytest.raises(KnowledgeConflict, match="unknown Procedure"):
        _router(root)


def test_metadata_lookup_returns_structured_candidates_without_ranking(tmp_path: Path) -> None:
    router = _router(_sources(tmp_path))
    procedure_matches = router.procedures.find(
        goal_type="service_discovery",
        environment="scoped_network_asset",
        produced_state="network.service",
        capability_id="network.service_discovery",
    )
    assert len(procedure_matches) == 1
    assert router.repository.list_documents(domain="network", protocol="tcp")
    assert (
        router.resolve(
            KnowledgeRequest(procedure_id=ProcedureId("procedure.network.service_discovery"))
        ).route
        is KnowledgeRoute.PROCEDURE_ID
    )
    assert (
        router.resolve(
            KnowledgeRequest(knowledge_id=KnowledgeId("knowledge.network.service_evidence"))
        ).route
        is KnowledgeRoute.KNOWLEDGE_ID
    )
    filtered = router.resolve(KnowledgeRequest(technology="tcp"))
    assert filtered.route is KnowledgeRoute.STRUCTURED
    assert filtered.procedures and not filtered.documents
    assert router.resolve(KnowledgeRequest(domain="network")).documents


def test_semantic_and_external_routes_are_explicitly_unavailable(tmp_path: Path) -> None:
    router = _router(_sources(tmp_path))
    exact = router.resolve(
        KnowledgeRequest(
            procedure_id=ProcedureId("procedure.network.service_discovery"),
            semantic_query="irrelevant fuzzy wording",
        )
    )
    assert exact.route is KnowledgeRoute.PROCEDURE_ID
    with pytest.raises(UnsupportedKnowledgeRoute, match="M18"):
        router.resolve(KnowledgeRequest(semantic_query="similar scanner failure"))
    with pytest.raises(UnsupportedKnowledgeRoute, match="external"):
        router.resolve(KnowledgeRequest(requires_current_external=True))
    with pytest.raises(ValueError, match="at least one metadata filter"):
        router.resolve(KnowledgeRequest())


def test_reload_failure_does_not_replace_prior_snapshot_or_promote_mission_data(
    tmp_path: Path,
) -> None:
    root = _sources(tmp_path)
    router = _router(root)
    (root / "mission-artifacts").mkdir()
    (root / "mission-artifacts" / "scan.md").write_text(
        "# target-specific scan with a secret", encoding="utf-8"
    )
    assert len(router.repository.list_documents()) == 1
    assert len(router.reload().repository.list_documents()) == 1
    (root / "reference" / REFERENCE_NAME).write_text("corrupted", encoding="utf-8")
    with pytest.raises(KnowledgeSourceError):
        router.reload()
    assert router.get_canonical(KnowledgeId("knowledge.network.service_evidence")) is not None


def test_refs_and_metadata_are_strict(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="KnowledgeId"):
        KnowledgeId("mission.not_knowledge")
    with pytest.raises(ValueError, match="ProcedureId"):
        ProcedureId("knowledge.not_procedure")
    with pytest.raises(ValidationError):
        KnowledgeRequest(
            procedure_id=ProcedureId("procedure.a"), knowledge_id=KnowledgeId("knowledge.b")
        )
    loader = CuratedMarkdownLoader(_sources(tmp_path))
    repository = KnowledgeRepository.from_directory(loader)
    procedures = ProcedureRegistry.from_directory(loader)
    assert len(repository.list_documents()) == 1
    assert len(procedures.find()) == 1
