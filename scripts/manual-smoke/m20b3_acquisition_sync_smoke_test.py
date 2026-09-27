"""Offline B3 validation: run the real Core/Node fixture integration once.

The integration harness is deliberately reused so manual and automated runs
exercise identical Router, Result-ingestion, and Artifact-sync paths.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "packages/core/tests"))
    from test_poc_acquisition_b3 import (
        test_real_b3_result_before_artifacts_and_replay_after_core_node_restart,
    )

    with tempfile.TemporaryDirectory(prefix="boberagent-m20b3-") as temporary:
        test_real_b3_result_before_artifacts_and_replay_after_core_node_restart(
            Path(temporary), "raw", emit_summary=True
        )
    print(
        "offline M20-B3 PASS: Result preceded both Artifacts; partial sync resumed; Core and Node reopened"
    )


if __name__ == "__main__":
    main()
