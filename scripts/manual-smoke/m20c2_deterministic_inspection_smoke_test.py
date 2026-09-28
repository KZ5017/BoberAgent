"""Fully offline C2 manual smoke over the shared synthetic ZIP/manifest scenario.

The test builds a completed acquisition, uses the real Core inspection services,
reopens Core and prints only bounded metadata. No real retained B5 source is read.
"""

from pathlib import Path

import pytest


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    scenario = root / "packages/core/tests/test_poc_inspection_c2.py"
    result = pytest.main(["-q", "-s", str(scenario) + "::test_offline_semantic_profile_reopen"])
    if result == pytest.ExitCode.OK:
        print("M20-C2 offline deterministic inspection/reopen smoke: PASS")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
