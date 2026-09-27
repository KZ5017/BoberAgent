"""B3 uses the existing Artifact protocol without joining Core and Node ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE_ACQUISITION = ROOT / "packages/core/src/boberagent_core/acquisitions"
NODE_ARTIFACTS = ROOT / "packages/execution-node/src/boberagent_execution_node/artifacts"


def _imports(root: Path) -> set[str]:
    imports: set[str] = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def test_core_acquisition_has_no_node_or_byte_transfer_implementation() -> None:
    imports = _imports(CORE_ACQUISITION)
    assert not any(
        name.startswith(("boberagent_execution_node", "boberagent_transport")) for name in imports
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in CORE_ACQUISITION.rglob("*.py"))
    assert "ArtifactTransferStart" not in source
    assert "ArtifactChunk" not in source
    assert "workspace_root" not in source
    assert "CoreArtifactService" in source


def test_node_artifact_sync_does_not_mutate_core_acquisition_domain() -> None:
    imports = _imports(NODE_ARTIFACTS)
    assert not any(name.startswith("boberagent_core") for name in imports)
