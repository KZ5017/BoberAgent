"""Offline manual C1 smoke using the migration-backed synthetic evidence scenario.

This is intentionally a thin runner for the focused integration scenario rather than a
second source-fixture builder. It never contacts GitHub, a Node, or MCP.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    scenario = root / "packages/core/tests/test_poc_inspection_c1.py"
    result = pytest.main(["-q", str(scenario) + "::test_completed_citation_reuse_and_reopen"])
    if result == pytest.ExitCode.OK:
        print("M20-C1 offline Artifact/manifest/citation/reopen smoke: PASS")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
