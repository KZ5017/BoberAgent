"""Offline B4 proof through the real Core/Node path and a test-owned curl shim.

The shim maps fixed GitHub URLs to local deterministic bytes; it has no network code.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "packages/core/tests"))
    from test_poc_acquisition_b4_integration import test_mocked_github_core_node_core

    with tempfile.TemporaryDirectory(prefix="boberagent-m20b4-") as temporary:
        test_mocked_github_core_node_core(
            Path(temporary), "success", "SOURCE_ACQUIRED", emit_summary=True
        )
    print(
        "offline M20-B4 PASS: fixed GitHub URLs, immutable SHA, real Node Artifacts, "
        "Core synchronization/finalization; no public request"
    )


if __name__ == "__main__":
    main()
