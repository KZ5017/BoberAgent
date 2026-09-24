"""Change detection and non-arbitrary Procedure candidate lookup."""

from __future__ import annotations

import shutil
from pathlib import Path

from boberagent_core.knowledge import (
    KnowledgeId,
    KnowledgeRouter,
    ProcedureDefinition,
    ProcedureId,
    ProcedureRegistry,
)

SOURCES = Path(__file__).resolve().parents[3] / "knowledge"


def test_revised_source_changes_hash_without_changing_logical_identity(tmp_path: Path) -> None:
    root = tmp_path / "curated"
    reference = root / "reference" / "item.md"
    procedure = root / "procedures" / "procedure.md"
    reference.parent.mkdir(parents=True)
    procedure.parent.mkdir()
    shutil.copyfile(SOURCES / "reference" / "network-service-evidence.md", reference)
    shutil.copyfile(SOURCES / "procedures" / "network-service-discovery.md", procedure)
    first = KnowledgeRouter.from_directory(root)
    knowledge_id = KnowledgeId("knowledge.network.service_evidence")
    original = first.get_canonical(knowledge_id)
    assert original is not None

    reference.write_text(
        reference.read_text(encoding="utf-8") + "\nA curated correction.\n", encoding="utf-8"
    )
    second = first.reload()
    revised = second.get_canonical(knowledge_id)
    assert revised is not None
    assert revised.knowledge_id == original.knowledge_id
    assert revised.version == original.version
    assert revised.provenance.content_sha256 != original.provenance.content_sha256
    assert first.get_canonical(knowledge_id) == original


def test_equally_applicable_procedures_are_returned_as_candidates_not_picked() -> None:
    source = SOURCES / "procedures" / "network-service-discovery.md"
    from boberagent_core.knowledge import CuratedMarkdownLoader

    original = CuratedMarkdownLoader(SOURCES).load_procedure(source)
    alternative = ProcedureDefinition.model_validate(
        {
            **original.model_dump(mode="python"),
            "procedure_id": ProcedureId("procedure.network.service_discovery_alternative"),
        }
    )
    registry = ProcedureRegistry((alternative, original))
    candidates = registry.find(goal_type="service_discovery", environment="scoped_network_asset")
    assert tuple(candidate.procedure_id for candidate in candidates) == (
        ProcedureId("procedure.network.service_discovery"),
        ProcedureId("procedure.network.service_discovery_alternative"),
    )
