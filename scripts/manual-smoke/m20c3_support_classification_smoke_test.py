"""Offline synthetic C1/C2/C3 history/reopen proof; no live source or execution."""

from pathlib import Path

import pytest


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    scenario = root / "packages/core/tests/test_poc_inspection_c3.py"
    code = pytest.main(["-q", "-s", str(scenario) + "::test_offline_classification_reopen"])
    if code == pytest.ExitCode.OK:
        print("M20-C3 offline AUTOMATIC/ASSISTED/UNSUPPORTED classification/reopen smoke: PASS")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
